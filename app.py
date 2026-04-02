import os
import time
import json
import html
import re
import threading
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from urllib.parse import quote_plus

from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS
import requests
from stability_engine import stabilize
from predictive_engine import predictive_analysis, check_early_warning

try:
    import google.generativeai as genai
except Exception:
    genai = None

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# =========================
# CONFIG
# =========================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", 10))
AI_TIMEOUT = int(os.environ.get("AI_TIMEOUT", 22))
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", 240))
USER_AGENT = "RealTimeJournal/2.0 (+https://www.realtimealerta.com.br)"

# Feeds reais: múltiplos RSS abertos + sísmico USGS
RSS_FEEDS = [
    {
        "name": "Google News World",
        "url": "https://news.google.com/rss?hl=pt-BR&gl=BR&ceid=BR:pt-419",
        "source": "Google News"
    },
    {
        "name": "Google News Geopolítica",
        "url": "https://news.google.com/rss/search?q=" + quote_plus("geopolítica OR geopolítica militar OR guerra OR míssil OR missile OR OTAN OR NATO OR Rússia OR China OR Taiwan OR Coreia do Norte") + "&hl=pt-BR&gl=BR&ceid=BR:pt-419",
        "source": "Google News"
    },
    {
        "name": "Google News Ciber",
        "url": "https://news.google.com/rss/search?q=" + quote_plus("ciberataque OR ransomware OR hackers OR infraestrutura crítica") + "&hl=pt-BR&gl=BR&ceid=BR:pt-419",
        "source": "Google News"
    },
    {
        "name": "NYT World",
        "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "source": "NYT"
    },
    {
        "name": "BBC World",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "source": "BBC"
    },
]

USGS_FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"

DEFAULT_NEWS = [
    {
        "title": "Escalada militar e tensão regional seguem sob monitoramento",
        "link": "https://www.reuters.com/",
        "description": "O painel opera com monitoramento reforçado quando feeds externos ficam indisponíveis.",
        "time": "LIVE",
        "level": "red",
        "region": "Global",
        "source": "Fallback"
    },
    {
        "title": "Infraestrutura crítica e cadeias logísticas entram em alerta",
        "link": "relatorio2.html",
        "description": "Cabos, energia, logística, satélites e comércio seguem no centro da leitura estratégica.",
        "time": "LIVE",
        "level": "orange",
        "region": "Global",
        "source": "Fallback"
    },
    {
        "title": "Mercados acompanham risco geopolítico e pressão energética",
        "link": "artigo6.html",
        "description": "Choques energéticos e pressão regional elevam o custo do erro político e operacional.",
        "time": "LIVE",
        "level": "orange",
        "region": "Global",
        "source": "Fallback"
    },
    {
        "title": "Taiwan, dissuasão no Indo-Pacífico e pressão naval seguem em foco",
        "link": "relatorio6.html",
        "description": "A leitura estratégica acompanha sinais graduais de escalada, pressão marítima e competição militar regional.",
        "time": "LIVE",
        "level": "red",
        "region": "Ásia-Pacífico",
        "source": "Fallback"
    },
    {
        "title": "Ataques digitais a serviços críticos ampliam o risco sistêmico",
        "link": "relatorio7.html",
        "description": "Infraestrutura crítica, telecom, energia e saúde permanecem como superfície prioritária de ataque e monitoramento.",
        "time": "LIVE",
        "level": "orange",
        "region": "Global",
        "source": "Fallback"
    }
]

DEFAULT_EVENTS = [
    {
        "lat": 48.37,
        "lon": 34.71,
        "level": "red",
        "title": "CONFLITO MILITAR",
        "description": "Ucrânia - Hostilidades ativas.",
        "region": "Leste Europeu",
        "source": "Monitoramento aberto",
        "link": "https://www.reuters.com/"
    },
    {
        "lat": 31.52,
        "lon": 34.45,
        "level": "red",
        "title": "ZONA DE GUERRA",
        "description": "Oriente Médio - Ofensivas e tensão regional.",
        "region": "Oriente Médio",
        "source": "Monitoramento aberto",
        "link": "https://www.aljazeera.com/"
    },
    {
        "lat": 35.68,
        "lon": 140.0,
        "level": "orange",
        "title": "ALERTA SÍSMICO",
        "description": "Atividade sísmica relevante no Pacífico.",
        "region": "Cinturão de Fogo",
        "source": "USGS",
        "link": "https://earthquake.usgs.gov/"
    }
]

REGION_HINTS = {
    "ukraine": ("Leste Europeu", 48.37, 34.71),
    "russia": ("Leste Europeu", 55.75, 37.61),
    "moscow": ("Leste Europeu", 55.75, 37.61),
    "iran": ("Oriente Médio", 32.42, 53.68),
    "israel": ("Oriente Médio", 31.52, 34.45),
    "gaza": ("Oriente Médio", 31.35, 34.30),
    "lebanon": ("Oriente Médio", 33.85, 35.86),
    "syria": ("Oriente Médio", 34.80, 38.99),
    "taiwan": ("Ásia-Pacífico", 23.70, 121.00),
    "china": ("Ásia-Pacífico", 35.86, 104.19),
    "south china sea": ("Ásia-Pacífico", 13.00, 114.00),
    "north korea": ("Ásia-Pacífico", 40.34, 127.51),
    "coreia do norte": ("Ásia-Pacífico", 40.34, 127.51),
    "korea": ("Ásia-Pacífico", 36.50, 127.80),
    "pakistan": ("Sul da Ásia", 30.37, 69.34),
    "india": ("Sul da Ásia", 20.59, 78.96),
    "red sea": ("Mar Vermelho", 20.00, 38.00),
    "mar vermelho": ("Mar Vermelho", 20.00, 38.00),
    "yemen": ("Península Arábica", 15.55, 48.52),
    "turkey": ("Anatólia", 38.96, 35.24),
    "europe": ("Europa", 50.11, 8.68),
    "africa": ("África", 1.65, 17.68),
    "japan": ("Ásia-Pacífico", 36.20, 138.25),
    "japão": ("Ásia-Pacífico", 36.20, 138.25),
    "chile": ("América do Sul", -33.45, -70.66),
    "brasil": ("América do Sul", -15.79, -47.88),
    "united states": ("América do Norte", 38.90, -77.04),
    "washington": ("América do Norte", 38.90, -77.04),
}

CATEGORY_DEFINITIONS = {
    "war": {
        "label": "GUERRA",
        "color": "#ff4040",
        "terms": [
            "war", "guerra", "attack", "attacks", "strike", "strikes", "bombing", "bombardeio",
            "missile", "míssil", "missil", "airstrike", "shelling", "invasion", "invasão",
            "frontline", "ofensiva", "retaliation", "retaliação", "nuclear", "drones", "drone"
        ],
    },
    "military": {
        "label": "MILITAR",
        "color": "#ff8a00",
        "terms": [
            "military", "militar", "army", "exército", "exercito", "troops", "tropas", "navy",
            "marinha", "air force", "força aérea", "forca aerea", "arsenal", "defense", "defesa",
            "exercise", "exercise", "drill", "mobilization", "porta-aviões", "submarine", "submarino"
        ],
    },
    "geopolitical": {
        "label": "GEOPOLÍTICA",
        "color": "#ffcc00",
        "terms": [
            "geopolit", "sanction", "sanções", "sanções", "diplomat", "ot an", "otan", "nato",
            "washington", "moscou", "moscow", "pequim", "beijing", "china", "russia", "rússia",
            "taiwan", "coreia do norte", "north korea", "indo-pacific", "indo-pacífico", "european union"
        ],
    },
    "infrastructure": {
        "label": "INFRAESTRUTURA",
        "color": "#00d5ff",
        "terms": [
            "cable", "submarine cable", "cabo submarino", "satellite", "satélite", "satelite", "pipeline",
            "porto", "port", "grid", "rede elétrica", "energia", "energy", "logistics", "logística",
            "semiconductor", "chip", "shipping", "infraestrutura", "infrastructure"
        ],
    },
    "cyber": {
        "label": "CIBER / HACKERS",
        "color": "#b14cff",
        "terms": [
            "cyber", "ciber", "hacker", "hackers", "ransomware", "malware", "phishing", "ddos",
            "spyware", "vazamento", "leak", "ciberataque", "cyberattack"
        ],
    },
    "financial_crime": {
        "label": "CORRUPÇÃO / LAVAGEM",
        "color": "#ffd84d",
        "terms": [
            "corruption", "corrupção", "corrupcao", "money laundering", "lavagem", "bribery", "propina",
            "fraude", "fraud", "embezzlement", "desvio", "cartel"
        ],
    },
    "violent_crime": {
        "label": "CRIME VIOLENTO / NARCO",
        "color": "#ff7a00",
        "terms": [
            "narco", "narcotráfico", "narcotrafico", "cartel", "crime organizado", "gang", "gangue",
            "homicide", "homicídio", "homicidio", "kidnapping", "sequestro"
        ],
    },
    "civil_unrest": {
        "label": "GUERRA CIVIL / COLAPSO",
        "color": "#ff4db8",
        "terms": [
            "civil war", "guerra civil", "unrest", "protest", "protestos", "collapse", "colapso",
            "state of emergency", "estado de emergência", "humanitarian crisis", "crise humanitária"
        ],
    },
    "seismic": {
        "label": "SÍSMICO",
        "color": "#35ff8a",
        "terms": [
            "earthquake", "terremoto", "seismic", "sísmico", "sismico", "quake", "tsunami", "volcano", "vulcão"
        ],
    },
}

executor = ThreadPoolExecutor(max_workers=10)
cache_lock = threading.Lock()
cache_store = {
    "intel_feed": {"expires": 0, "value": None},
    "threat_summary": {"expires": 0, "value": None},
    "critical_news": {"expires": 0, "value": None},
}

# =========================
# GEMINI INIT
# =========================
model = None
if GEMINI_API_KEY and genai is not None:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
    except Exception:
        model = None

# =========================
# HELPERS
# =========================
def now_ts() -> float:
    return time.time()


def safe_get_cache(key: str):
    with cache_lock:
        item = cache_store.get(key)
        if item and item["expires"] > now_ts():
            return item["value"]
    return None


def safe_set_cache(key: str, value):
    with cache_lock:
        cache_store[key] = {"expires": now_ts() + CACHE_TTL_SECONDS, "value": value}


def sanitize_text(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def http_get_json(url: str):
    r = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.json()


def http_get_text(url: str):
    r = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.text


def run_with_timeout(fn, timeout_seconds, *args, **kwargs):
    future = executor.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout_seconds)
    except FuturesTimeout:
        return None
    except Exception:
        return None


def infer_region_and_coords(text: str):
    text_l = (text or "").lower()
    for key, value in REGION_HINTS.items():
        if key in text_l:
            return value
    return ("Global", 20.0, 0.0)


def classify_level(title: str, description: str = "") -> str:
    scores = classify_categories(f"{title} {description}")
    if scores["war"] >= 2:
        return "red"
    if scores["military"] >= 2 or scores["geopolitical"] >= 2:
        return "orange"
    if scores["cyber"] >= 2:
        return "purple"
    if scores["financial_crime"] >= 2:
        return "yellow"
    if scores["infrastructure"] >= 2:
        return "blue"
    return "green"


def classify_categories(text: str):
    normalized = sanitize_text(text).lower()
    counter = Counter({key: 0 for key in CATEGORY_DEFINITIONS.keys()})
    for key, cfg in CATEGORY_DEFINITIONS.items():
        for term in cfg["terms"]:
            if term.lower() in normalized:
                counter[key] += 1
    return counter


def get_primary_category(text: str) -> str:
    scores = classify_categories(text)
    if not any(scores.values()):
        return "geopolitical"
    return scores.most_common(1)[0][0]


def build_event_from_news_item(item: dict):
    region, lat, lon = infer_region_and_coords(
        f"{item.get('title', '')} {item.get('description', '')} {item.get('region', '')} {item.get('source', '')}"
    )
    domain = get_primary_category(f"{item.get('title', '')} {item.get('description', '')}")
    title_prefix = {
        "seismic": "ALERTA SÍSMICO",
        "infrastructure": "INFRAESTRUTURA CRÍTICA",
        "military": "CONFLITO / TENSÃO",
        "war": "ZONA DE GUERRA",
        "cyber": "CIBERATAQUE / VAZAMENTO",
        "financial_crime": "CRIME FINANCEIRO",
        "violent_crime": "CRIME ORGANIZADO",
        "civil_unrest": "COLAPSO / CONVULSÃO",
        "geopolitical": "MONITORAMENTO GEOPOLÍTICO",
    }.get(domain, "MONITORAMENTO")
    category_scores = classify_categories(f"{item.get('title', '')} {item.get('description', '')}")
    severity_score = 92 if item.get("level") == "red" else 74 if item.get("level") == "orange" else 58 if item.get("level") == "purple" else 42
    return {
        "lat": lat,
        "lon": lon,
        "level": item.get("level", "orange"),
        "title": title_prefix,
        "description": (item.get("title", "") or "")[:180],
        "region": region,
        "source": item.get("source", "Feed aberto"),
        "link": item.get("link", "#"),
        "type": domain,
        "score": severity_score + min(6, sum(category_scores.values()) * 2)
    }


# =========================
# FEED FETCHERS
# =========================
def parse_rss_items(xml_text: str, source_name: str):
    root = ET.fromstring(xml_text)
    items = []
    for item in root.findall('.//item')[:12]:
        title = sanitize_text(item.findtext('title', ''))
        link = sanitize_text(item.findtext('link', ''))
        description = sanitize_text(item.findtext('description', ''))
        pub_date = sanitize_text(item.findtext('pubDate', ''))
        if not title:
            continue
        level = classify_level(title, description)
        region, _, _ = infer_region_and_coords(f"{title} {description}")
        items.append({
            "title": title,
            "description": description[:260] if description else "Leitura situacional resumida com contexto operacional e impacto potencial.",
            "link": link or '#',
            "time": pub_date[:25] if pub_date else 'LIVE',
            "level": level,
            "region": region,
            "source": source_name,
        })
    return items


def fetch_rss_feed(feed_cfg: dict):
    xml_text = http_get_text(feed_cfg['url'])
    return parse_rss_items(xml_text, feed_cfg['source'])


def fetch_all_news():
    results = []
    for feed in RSS_FEEDS:
        partial = run_with_timeout(fetch_rss_feed, HTTP_TIMEOUT + 2, feed)
        if partial:
            results.extend(partial)

    if not results:
        return DEFAULT_NEWS.copy()

    dedup = []
    seen = set()
    for item in results:
        key = (item['title'].strip().lower(), item.get('source', '').strip().lower())
        if key not in seen and item['title']:
            seen.add(key)
            dedup.append(item)

    # prioridade: vermelho > laranja > roxo > azul > amarelo > verde
    level_order = {'red': 0, 'orange': 1, 'purple': 2, 'blue': 3, 'yellow': 4, 'green': 5}
    dedup.sort(key=lambda x: (level_order.get(x.get('level', 'green'), 9), x.get('title', '')))
    return dedup[:16]


def fetch_earthquakes():
    data = run_with_timeout(http_get_json, HTTP_TIMEOUT + 3, USGS_FEED)
    if not data or 'features' not in data:
        return []
    events = []
    for feat in data['features'][:10]:
        try:
            coords = feat['geometry']['coordinates']
            lon, lat = coords[0], coords[1]
            mag = feat['properties'].get('mag', 0) or 0
            place = feat['properties'].get('place', 'Atividade sísmica')
            link = feat['properties'].get('url', 'https://earthquake.usgs.gov/')
            level = 'red' if mag >= 6.0 else 'orange'
            events.append({
                'lat': lat,
                'lon': lon,
                'level': level,
                'title': 'ALERTA SÍSMICO',
                'description': f'{place} • magnitude {mag}',
                'region': 'Cinturão de Fogo' if abs(lon) > 100 else 'Monitoramento Sísmico',
                'source': 'USGS',
                'link': link,
                'type': 'seismic',
                'score': 88 if mag >= 6.0 else 64,
            })
        except Exception:
            continue
    return events


# =========================
# AI LAYER
# =========================
def local_analyst_fallback(prompt: str, reason: str | None = None) -> str:
    lower = (prompt or '').lower()

    contexto = 'Há monitoramento reforçado, com leitura conservadora e foco em vetores de escalada, logística e impacto regional.'
    risco = 'Risco moderado, com possibilidade de deterioração rápida se houver novo incidente militar, diplomático ou cibernético.'
    vetores = 'Vetores principais: desinformação, pressão econômica, movimentação militar, ataques cibernéticos e incidentes em infraestrutura crítica.'
    impactos = 'Impactos potenciais: volatilidade em energia, comércio, cadeias logísticas, seguros, câmbio e percepção de risco internacional.'

    if any(k in lower for k in ['china', 'eua', 'taiwan', 'mar do sul', 'indo-pacífico']):
        contexto = 'O eixo China-EUA segue como principal foco sistêmico, com Taiwan e o Indo-Pacífico como zonas sensíveis de dissuasão, pressão naval e competição tecnológica.'
        risco = 'Risco elevado de incidente localizado, mas sem indicação automática de guerra aberta no curtíssimo prazo.'
        vetores = 'Vetores principais: exercícios militares, sanções, semicondutores, bloqueio parcial, pressão naval e erro de cálculo entre forças destacadas.'
        impactos = 'Impactos potenciais: chips, transporte marítimo, seguro global, cadeias industriais e reprecificação de ativos de risco.'
    elif any(k in lower for k in ['rússia', 'russia', 'ucrânia', 'ucrania', 'otan', 'europa']):
        contexto = 'O teatro europeu continua marcado por desgaste prolongado, drones, pressão sobre defesa aérea e sensibilidade política entre OTAN, Rússia e fronteiras do leste.'
        risco = 'Risco alto de escalada localizada e ataques de saturação, mas sem sinal conclusivo de expansão imediata para guerra continental.'
        vetores = 'Vetores principais: drones de longo alcance, logística militar, energia, munição, sabotagem e pressão política interna.'
        impactos = 'Impactos potenciais: energia, alimentos, fertilizantes, frete, orçamento de defesa e estabilidade política regional.'
    elif any(k in lower for k in ['iran', 'israel', 'hormuz', 'mar vermelho', 'oriente médio', 'oriente medio']):
        contexto = 'O Oriente Médio segue com forte sensibilidade estratégica por causa de rotas marítimas, energia, proxies armados e risco de arrasto regional.'
        risco = 'Risco alto de choque logístico e de energia, especialmente se houver ataque a rotas, refinarias, portos ou infraestrutura crítica.'
        vetores = 'Vetores principais: Hormuz, Mar Vermelho, drones, mísseis, retaliação indireta e pressão sobre aliados.'
        impactos = 'Impactos potenciais: petróleo, gás, seguro marítimo, frete, inflação internacional e cadeias de suprimento.'
    elif any(k in lower for k in ['ciber', 'hacker', 'ransomware', 'infraestrutura', 'hospital', 'energia', 'apagão', 'apagao']):
        contexto = 'A frente cibernética continua assimétrica, barata e escalável, com capacidade de causar disrupção sem confronto militar clássico.'
        risco = 'Risco elevado para infraestrutura crítica e serviços essenciais, sobretudo onde há baixa resiliência operacional.'
        vetores = 'Vetores principais: ransomware, intrusão em cadeias de fornecedores, sabotagem discreta, vazamento de dados e ataques oportunistas.'
        impactos = 'Impactos potenciais: hospitais, telecom, energia, logística, confiança pública e custos regulatórios.'

    linhas = [
        'Contexto: ' + contexto,
        'Risco: ' + risco,
        'Vetores de escalada: ' + vetores,
        'Impactos: ' + impactos,
        'Leitura operacional: manter monitoramento contínuo, validar fontes e evitar extrapolação sem novo fato confirmatório.'
    ]

    if reason:
        linhas.append('Observação técnica: a resposta foi entregue pelo modo local de contingência porque a IA avançada ficou temporariamente indisponível.')

    return '

'.join(linhas)


def ai_answer(prompt: str) -> str:
    if not model:
        return local_analyst_fallback(prompt, 'model_unavailable')

    system_prompt = f'''
Você é o Analista Sênior IA do Real Time Journal.
Responda em português do Brasil.
Seja objetivo, analítico, claro e sem sensacionalismo.
Aponte: contexto, risco, vetores de escalada, impactos regionais e globais.
Pergunta do usuário: {prompt}
'''
    try:
        result = model.generate_content(system_prompt)
        text = getattr(result, 'text', None)
        if text and text.strip():
            return text.strip()
    except Exception:
        return local_analyst_fallback(prompt, 'gemini_exception')

    return local_analyst_fallback(prompt, 'empty_response')


def conservative_blend_score(base_value, ai_value, ai_weight=0.18, max_delta=12):
    try:
        base = float(base_value)
        ai = float(ai_value)
    except Exception:
        return int(round(base_value))

    ai = max(0.0, min(100.0, ai))
    blended = (base * (1 - ai_weight)) + (ai * ai_weight)
    if blended > base + max_delta:
        blended = base + max_delta
    elif blended < base - max_delta:
        blended = base - max_delta
    return int(round(max(0.0, min(100.0, blended))))


def ai_enrich_summary(news: list, base_summary: dict) -> dict:
    if not model or not news:
        return base_summary

    compact_news = [
        {
            'title': n.get('title'),
            'description': n.get('description', '')[:160],
            'level': n.get('level'),
            'region': n.get('region'),
            'source': n.get('source')
        }
        for n in news[:8]
    ]
    prompt = f'''
Analise as headlines abaixo e devolva SOMENTE JSON válido.
Estrutura exata:
{{
  "global_level": "critical|elevated|moderate",
  "global_label": "texto curto",
  "defcon_label": "Nível Verde|Nível Amarelo|Nível Laranja|Nível Vermelho",
  "message": "uma frase curta",
  "scores": {{
    "war": 0,
    "military": 0,
    "geopolitical": 0,
    "infrastructure": 0,
    "cyber": 0,
    "financial_crime": 0,
    "violent_crime": 0,
    "civil_unrest": 0,
    "seismic": 0
  }},
  "hotspots": [
    {{"region": "nome", "score": 0, "reason": "texto curto"}}
  ]
}}
Eventos:
{json.dumps(compact_news, ensure_ascii=False)}
'''
    try:
        result = model.generate_content(prompt)
        text = getattr(result, 'text', '') or ''
        match = re.search(r'\{.*\}', text, re.S)
        if not match:
            return base_summary
        parsed = json.loads(match.group(0))
        for field in ['global_level', 'global_label', 'defcon_label', 'message']:
            if parsed.get(field):
                base_summary[field] = parsed[field]
        scores = parsed.get('scores', {}) or {}
        for key in base_summary['scores'].keys():
            if isinstance(scores.get(key), int):
                base_summary['scores'][key] = conservative_blend_score(base_summary['scores'][key], scores[key])
        hotspots = parsed.get('hotspots') or []
        if isinstance(hotspots, list) and hotspots:
            cleaned = []
            for item in hotspots[:5]:
                if isinstance(item, dict):
                    cleaned.append({
                        'region': str(item.get('region', 'Global'))[:60],
                        'score': max(0, min(100, int(item.get('score', 0) or 0))),
                        'reason': str(item.get('reason', 'atividade crítica'))[:120]
                    })
            if cleaned:
                base_summary['hotspots'] = cleaned
        return base_summary
    except Exception:
        return base_summary




def safe_slug(value):
    value = (value or '').strip().lower()
    value = re.sub(r'[^a-z0-9áàâãéèêíïóôõöúçñ\s-]', '', value)
    replacements = str.maketrans('áàâãäéèêëíìïîóòôõöúùüûçñ', 'aaaaaeeeeiiiiooooouuuucn')
    value = value.translate(replacements)
    value = re.sub(r'[-\s]+', '-', value).strip('-')
    return value or 'item'


def build_analysis_url(file_name):
    page = ANALYSIS_BY_FILE.get(file_name)
    return f'/analise/{page["slug"]}.html' if page else file_name


def build_news_slug(item, index=0):
    base = safe_slug(item.get('title') or item.get('tag') or f'alerta-{index + 1}')
    return f'{base}-{index + 1}' if len(base) < 12 else base


def inject_seo_into_html(raw_html, canonical_url, title, description):
    seo_block = (
        f'<link rel="canonical" href="{html.escape(canonical_url, quote=True)}">\n'
        f'<meta property="og:type" content="article">\n'
        f'<meta property="og:title" content="{html.escape(title, quote=True)}">\n'
        f'<meta property="og:description" content="{html.escape(description, quote=True)}">\n'
        f'<meta property="og:url" content="{html.escape(canonical_url, quote=True)}">\n'
        f'<meta name="twitter:card" content="summary_large_image">\n'
        f'<meta name="twitter:title" content="{html.escape(title, quote=True)}">\n'
        f'<meta name="twitter:description" content="{html.escape(description, quote=True)}">'
    )
    if '</head>' in raw_html:
        raw_html = raw_html.replace('</head>', seo_block + '\n</head>', 1)
    raw_html = raw_html.replace('href="index.html"', 'href="/"')
    raw_html = raw_html.replace("href='index.html'", "href='/'")
    return raw_html




def derive_news_intelligence(item):
    title = str(item.get("title", "")).strip()
    description = str(item.get("description", "")).strip()
    region = str(item.get("region", "Global")).strip()
    tag = str(item.get("tag") or infer_critical_tag(item)).strip()
    level = str(item.get("level", "green")).lower()
    source = str(item.get("source", "Fonte aberta")).strip()

    title_lower = f"{title} {description} {region}".lower()

    if any(term in title_lower for term in ["drone", "míssil", "missil", "missile", "patriot", "thaad", "aegis"]):
        context = "O item aponta para evolução de capacidades de ataque ou defesa, algo relevante para medir saturação, proteção em camadas e ritmo de adaptação operacional."
    elif any(term in title_lower for term in ["taiwan", "mar do sul da china", "china", "indo-pacífico", "indo-pacific"]):
        context = "O tema se conecta ao tabuleiro do Indo-Pacífico, onde pressão gradual, presença naval e sinalização militar costumam alterar percepção de risco mesmo sem confronto aberto imediato."
    elif any(term in title_lower for term in ["hormuz", "mar vermelho", "shipping", "navio", "porto", "logística", "logistica"]):
        context = "O foco recai sobre corredores marítimos e gargalos logísticos, que têm efeito direto sobre energia, seguros, frete e resiliência comercial."
    elif any(term in title_lower for term in ["ciber", "cyber", "ransomware", "hack", "hospital", "energia", "infraestrutura"]):
        context = "A leitura estratégica envolve vulnerabilidade de serviços críticos, continuidade operacional e possibilidade de efeitos em cascata sobre telecomunicações, saúde, energia e transporte."
    else:
        context = "O alerta entra no radar por combinar relevância regional, potencial de escalada e necessidade de acompanhamento contínuo das fontes abertas."

    if level == 'red':
        impact = "Impacto potencial elevado: o sinal sugere necessidade de observação prioritária, porque pode alterar postura militar, cadeias de suprimento ou percepção de estabilidade regional em curto prazo."
    elif level == 'orange':
        impact = "Impacto potencial alto: o evento merece acompanhamento próximo, pois pode ampliar tensão regional, gerar resposta política ou pressionar infraestrutura e mercados."
    elif level == 'purple':
        impact = "Impacto potencial moderado: o sinal ainda depende de confirmação e continuidade, mas já oferece material útil para leitura antecipada de tendência."
    else:
        impact = "Impacto potencial monitorado: o evento ajuda a compor quadro situacional mais amplo e pode ganhar relevância caso novos sinais apareçam."

    summary = description or f"Alerta classificado como {tag.lower()} em {region}, monitorado a partir de fontes abertas e priorizado pelo sistema conforme severidade, região e peso estratégico."

    source_note = f"Origem principal do sinal: {source}. O conteúdo é tratado editorialmente para acrescentar contexto, leitura situacional e continuidade de análise sem perder o estilo OSINT do projeto."

    return {
        'summary': summary,
        'context': context,
        'impact': impact,
        'source_note': source_note,
    }

def render_news_page(item, slug):
    title = item.get('title', 'Notícia crítica')
    description = item.get('description') or 'Leitura crítica do monitoramento em tempo real do Real Time Journal.'
    region = item.get('region', 'Global')
    level = item.get('level', 'orange')
    tag = item.get('tag') or infer_critical_tag(item)
    score = item.get('score', 0)
    intel = derive_news_intelligence(item)
    source = item.get('source', 'Real Time Journal')
    external_link = item.get('original_link') or item.get('source_link') or '#'
    analysis_link = item.get('analysis_link')
    level_label = {'red': 'CRÍTICO', 'orange': 'ALTO', 'purple': 'ATENÇÃO'}.get(str(level).lower(), 'MONITORADO')
    canonical_url = request.url
    source_button = ''
    if external_link and external_link not in ('#', canonical_url):
        source_button = f'<a href="{html.escape(external_link, quote=True)}" target="_blank" rel="noopener noreferrer" class="rtj-btn rtj-btn-secondary">Abrir fonte original</a>'
    analysis_button = ''
    if analysis_link:
        analysis_button = f'<a href="{html.escape(analysis_link, quote=True)}" class="rtj-btn">Abrir análise completa</a>'
    cta_row = ''.join([analysis_button, source_button, '<a href="/" class="rtj-btn rtj-btn-secondary">Voltar para a home</a>'])
    return f"""<!DOCTYPE html>
<html lang=\"pt-br\">
<head>
<meta charset=\"UTF-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
<title>{html.escape(title)} | Real Time Journal</title>
<meta name=\"description\" content=\"{html.escape(description, quote=True)}\">
<link rel=\"canonical\" href=\"{html.escape(canonical_url, quote=True)}\">
<meta property=\"og:type\" content=\"article\">
<meta property=\"og:title\" content=\"{html.escape(title, quote=True)}\">
<meta property=\"og:description\" content=\"{html.escape(description, quote=True)}\">
<meta property=\"og:url\" content=\"{html.escape(canonical_url, quote=True)}\">
<link href=\"https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Inter:wght@400;600;700;900&display=swap\" rel=\"stylesheet\">
<link rel=\"stylesheet\" href=\"/v6-warroom.css\">
<style>
body{{font-family:Inter,Arial,sans-serif;line-height:1.8}}
.page{{max-width:980px;margin:0 auto;padding:36px 22px 80px}}
.topbar{{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:20px 0 12px;border-bottom:1px solid rgba(255,255,255,.09)}}
.brand{{font-family:'Playfair Display',serif;font-size:32px;font-weight:900;color:#fff;text-decoration:none}}
.badge{{display:inline-flex;gap:10px;align-items:center;padding:8px 14px;border-radius:999px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.09);font-size:11px;letter-spacing:.18em;text-transform:uppercase}}
.hero{{padding:34px 0 12px}}
.hero h1{{font-family:'Playfair Display',serif;font-size:clamp(2.3rem,4vw,4rem);line-height:1.05;margin:0 0 16px;color:#fff}}
.lead{{font-size:1.08rem;color:#cdd7e1;max-width:850px}}
.meta{{display:flex;flex-wrap:wrap;gap:12px;margin:22px 0 28px}}
.meta-card{{padding:14px 16px;border-radius:16px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);min-width:170px}}
.meta-card span{{display:block;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#96a7b8;margin-bottom:6px}}
.meta-card strong{{font-size:1rem;color:#fff}}
.article-box{{background:linear-gradient(180deg, rgba(12,17,23,.96), rgba(7,10,15,.98));border:1px solid rgba(255,255,255,.08);border-radius:22px;padding:26px;box-shadow:0 20px 60px rgba(0,0,0,.28)}}
.article-box p{{margin:0 0 18px;color:#d7e1ea}}
.section-title{{font-family:'Playfair Display',serif;font-size:1.7rem;color:#fff;margin:28px 0 14px}}
.cta-row{{display:flex;flex-wrap:wrap;gap:12px;margin-top:26px}}
.rtj-btn{{display:inline-flex;align-items:center;justify-content:center;padding:12px 18px;border-radius:14px;background:#a6191e;color:#fff;text-decoration:none;font-weight:900;text-transform:uppercase;letter-spacing:.08em;border:1px solid rgba(255,255,255,.08)}}
.rtj-btn-secondary{{background:transparent;border:1px solid rgba(255,255,255,.18)}}
.backlinks{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-top:30px}}
.backlinks a{{display:block;padding:16px 18px;border-radius:16px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);text-decoration:none;color:#d7e1ea}}
.small-note{{color:#93a5b7;font-size:.95rem}}
</style>
</head>
<body class=\"war-room-real\">
<div class=\"page\">
<div class=\"topbar\"><a class=\"brand\" href=\"/\">Real Time Journal</a><div class=\"badge\">Notícia crítica • URL individual</div></div>
<section class=\"hero\">
<div class=\"badge\">{html.escape(tag)} • {html.escape(level_label)}</div>
<h1>{html.escape(title)}</h1>
<p class=\"lead\">{html.escape(description)}</p>
<div class=\"meta\">
<div class=\"meta-card\"><span>Região</span><strong>{html.escape(region)}</strong></div>
<div class=\"meta-card\"><span>Score</span><strong>{str(score).zfill(2)}</strong></div>
<div class=\"meta-card\"><span>Origem</span><strong>{html.escape(source)}</strong></div>
<div class=\"meta-card\"><span>Slug</span><strong>/noticia/{html.escape(slug)}</strong></div>
</div>
</section>
<section class=\"article-box\">
<h2 class=\"section-title\">Resumo editorial</h2>
<p>Esta página individual foi gerada automaticamente para transformar alertas críticos em URLs próprias, facilitando indexação, leitura contextual e organização editorial do projeto sem alterar a aparência principal da home.</p>
<p>{html.escape(description)}</p>
<p class=\"small-note\">Sinal classificado como <strong>{html.escape(level_label)}</strong> na região <strong>{html.escape(region)}</strong>. Quando existir um relatório aprofundado relacionado, ele aparece abaixo como continuação de leitura.</p>
<div class=\"cta-row\">{cta_row}</div>
<div class=\"backlinks\">
<a href=\"/analise/escudos-da-america\"><strong>Escudos da América</strong><br><span class=\"small-note\">Defesa em camadas e arquitetura antimíssil.</span></a>
<a href=\"/analise/ucrania-e-guerra-de-drones\"><strong>Ucrânia e drones</strong><br><span class=\"small-note\">Saturação, defesa aérea e desgaste de estoques.</span></a>
<a href=\"/analise/taiwan-e-mar-do-sul-da-china\"><strong>Taiwan e Mar do Sul da China</strong><br><span class=\"small-note\">Zona cinzenta, dissuasão e pressão militar gradual.</span></a>
</div>
</section>
</div>
</body>
</html>"""

def infer_critical_tag(item, hits=None):
    region = (item.get('region') or '').lower()
    title = f"{item.get('title', '')} {item.get('description', '')}".lower()
    if hits is None:
        hits = classify_categories(title + ' ' + region)

    if hits.get('war') or 'drone' in title or 'míssil' in title or 'missile' in title:
        return 'Conflito Ativo'
    if hits.get('military') or 'military' in title or 'defense' in title or 'defesa' in title:
        return 'Militar'
    if hits.get('cyber'):
        return 'Ciber'
    if hits.get('infrastructure'):
        return 'Infraestrutura'
    if hits.get('financial_crime'):
        return 'Financeiro'
    if 'ártico' in region or 'arctic' in title:
        return 'Ártico'
    if 'taiwan' in title or 'indo' in title or 'ásia' in region or 'asia' in region:
        return 'Indo-Pacífico'
    if 'oriente médio' in region or 'middle east' in title or 'beirut' in title:
        return 'Oriente Médio'
    return 'Geopolítica'




ANALYSIS_PAGES = [
    {"type": "artigo", "file": "artigo3.html", "slug": "uma-possivel-terceira-guerra-mundial", "title": "Uma Possível Terceira Guerra Mundial", "description": "Análise sobre sinais, riscos e limites de uma escalada global entre grandes potências."},
    {"type": "artigo", "file": "artigo4.html", "slug": "conflitos-modernos-e-o-novo-cenario-geopolitico", "title": "Conflitos Modernos e o Novo Cenário Geopolítico", "description": "Leitura sobre a transformação dos conflitos contemporâneos, competição estratégica e novos vetores de instabilidade."},
    {"type": "artigo", "file": "artigo5.html", "slug": "infraestrutura-critica-na-geopolitica-moderna", "title": "Infraestrutura Crítica na Geopolítica Moderna", "description": "Como cabos, satélites, energia e logística moldam poder, resiliência e vulnerabilidade global."},
    {"type": "artigo", "file": "artigo6.html", "slug": "economia-global-em-tempos-de-instabilidade", "title": "Economia Global em Tempos de Instabilidade", "description": "Pressão energética, cadeias logísticas e impactos econômicos em cenários de instabilidade geopolítica."},
    {"type": "artigo", "file": "artigo7.html", "slug": "tecnologia-e-guerra-no-seculo-xxi", "title": "Tecnologia e Guerra no Século XXI", "description": "Drones, sensores, guerra eletrônica e a transformação tecnológica do campo de batalha."},
    {"type": "artigo", "file": "artigo8.html", "slug": "cadeias-logisticas-globais-e-seguranca-internacional", "title": "Cadeias Logísticas Globais e Segurança Internacional", "description": "Rotas marítimas, gargalos e exposição sistêmica das cadeias globais."},
    {"type": "relatorio", "file": "relatorio1.html", "slug": "crise-dos-semicondutores", "title": "Relatório 01 • Crise dos Semicondutores", "description": "Sensibilidade geopolítica da cadeia tecnológica e efeitos estratégicos sobre indústria e defesa."},
    {"type": "relatorio", "file": "relatorio2.html", "slug": "cabos-submarinos-e-satelites", "title": "Relatório 02 • Cabos Submarinos e Satélites", "description": "Infraestrutura crítica da era digital, dependência global e riscos de interrupção."},
    {"type": "relatorio", "file": "relatorio3.html", "slug": "escudos-da-america", "title": "Relatório 03 • Escudos da América", "description": "Patriot, THAAD, Aegis, GMD e a arquitetura antimíssil dos Estados Unidos."},
    {"type": "relatorio", "file": "relatorio4.html", "slug": "ucrania-e-guerra-de-drones", "title": "Relatório 04 • Ucrânia e Guerra de Drones", "description": "Saturação, defesa aérea, custo de interceptação e mudança do equilíbrio operacional."},
    {"type": "relatorio", "file": "relatorio5.html", "slug": "hormuz-e-mar-vermelho", "title": "Relatório 05 • Hormuz e Mar Vermelho", "description": "Risco sistêmico para energia, seguros, frete e rotas alternativas."},
    {"type": "relatorio", "file": "relatorio6.html", "slug": "taiwan-e-mar-do-sul-da-china", "title": "Relatório 06 • Taiwan e Mar do Sul da China", "description": "Zona cinzenta, dissuasão e sinais graduais de escalada no Indo-Pacífico."},
    {"type": "relatorio", "file": "relatorio7.html", "slug": "infraestrutura-critica-e-ciberataques", "title": "Relatório 07 • Infraestrutura Crítica e Ciberataques", "description": "Hardening, superfície de ataque e leitura estratégica de ciberameaças."},
    {"type": "relatorio", "file": "relatorio8.html", "slug": "satelites-comerciais-e-osint-orbital", "title": "Relatório 08 • Satélites Comerciais e OSINT Orbital", "description": "O valor operacional das imagens comerciais e do monitoramento orbital."},
    {"type": "relatorio", "file": "relatorio9.html", "slug": "cabos-submarinos-e-resiliencia", "title": "Relatório 09 • Cabos Submarinos e Resiliência", "description": "99% do tráfego global, vulnerabilidades e resposta estatal."},
    {"type": "relatorio", "file": "relatorio10.html", "slug": "golden-dome-e-defesa-do-territorio", "title": "Relatório 10 • Golden Dome e Defesa do Território", "description": "Sensores hipersônicos, defesa em camadas e proteção do território."},
    {"type": "relatorio", "file": "relatorio11.html", "slug": "russia-china-e-coreia-do-norte", "title": "Relatório 11 • Rússia, China e Coreia do Norte", "description": "Eixo nuclear, dissuasão e vetores estratégicos contemporâneos."},
]

ANALYSIS_BY_SLUG = {item["slug"]: item for item in ANALYSIS_PAGES}
ANALYSIS_BY_FILE = {item["file"]: item for item in ANALYSIS_PAGES}

PROJECT_CRITICAL_REPORTS = [
    {
        'title': 'Escudos da América, Golden Dome e defesa em camadas',
        'description': 'Leitura editorial sobre Patriot, THAAD, Aegis, GMD, sensores e a expansão da arquitetura antimíssil dos EUA.',
        'region': 'América do Norte',
        'level': 'orange',
        'link': 'noticia/escudos-da-america-golden-dome-e-defesa-em-camadas.html',
        'tag': 'Relatório estratégico',
        'score': 92,
    },
    {
        'title': 'Ucrânia, drones de saturação e evolução do combate',
        'description': 'Panorama sobre UAVs, defesa aérea, profundidade operacional e mudança na relação custo-efeito do conflito.',
        'region': 'Leste Europeu',
        'level': 'red',
        'link': 'noticia/ucrania-drones-de-saturacao-e-evolucao-do-combate.html',
        'tag': 'Conflito ativo',
        'score': 95,
    },
    {
        'title': 'Hormuz, Mar Vermelho e risco sistêmico para comércio',
        'description': 'Impacto sobre energia, seguros, frete, rotas alternativas e exposição logística em corredores marítimos.',
        'region': 'Oriente Médio',
        'level': 'orange',
        'link': 'noticia/hormuz-mar-vermelho-e-risco-sistemico-para-comercio.html',
        'tag': 'Marítimo e energia',
        'score': 90,
    },
    {
        'title': 'Taiwan, Mar do Sul da China e zona cinzenta',
        'description': 'Pressão militar, submarinos, radar de tiro, dissuasão e sinais graduais de escalada no Indo-Pacífico.',
        'region': 'Ásia-Pacífico',
        'level': 'red',
        'link': 'noticia/taiwan-mar-do-sul-da-china-e-zona-cinzenta.html',
        'tag': 'Indo-Pacífico',
        'score': 94,
    },
    {
        'title': 'Hospitais, indústria e ataque digital a serviços críticos',
        'description': 'Ciberameaças oportunistas, hardening e vulnerabilidades em saúde, logística, telecom e energia.',
        'region': 'Global',
        'level': 'orange',
        'link': 'noticia/hospitais-industria-e-ataque-digital-a-servicos-criticos.html',
        'tag': 'Ciber e infraestrutura',
        'score': 89,
    },
]

DYNAMIC_CRITICAL_FALLBACK = [
    {
        'title': item['title'],
        'description': item.get('description', 'Evento crítico em monitoramento.'),
        'region': item.get('region', 'Global'),
        'level': item.get('level', 'orange'),
        'link': item.get('link', '#'),
        'tag': infer_critical_tag(item),
        'score': max(60, 94 - (idx * 5)),
    }
    for idx, item in enumerate(DEFAULT_NEWS[:5])
]


def ensure_critical_items(dynamic_items, static_items, limit=10):
    dynamic = list(dynamic_items[:5])
    fallback_pool = [dict(item) for item in DYNAMIC_CRITICAL_FALLBACK]

    used_titles = {item.get('title', '').strip().lower() for item in dynamic if item.get('title')}
    for item in fallback_pool:
        title_key = item.get('title', '').strip().lower()
        if len(dynamic) >= 5:
            break
        if title_key and title_key not in used_titles:
            dynamic.append(item)
            used_titles.add(title_key)

    while len(dynamic) < 5 and fallback_pool:
        seed = dict(fallback_pool[(len(dynamic)) % len(fallback_pool)])
        seed['title'] = f"{seed.get('title', 'Alerta crítico')} • complemento {len(dynamic) + 1}"
        dynamic.append(seed)

    combined = dynamic[:5] + list(static_items[:5])
    if len(combined) < limit:
        refill = list(static_items[:5]) + fallback_pool
        idx = 0
        while len(combined) < limit and refill:
            seed = dict(refill[idx % len(refill)])
            seed['title'] = f"{seed.get('title', 'Relatório estratégico')} • adicional {len(combined) + 1}"
            combined.append(seed)
            idx += 1

    return combined[:limit]


def build_global_war_map_payload(events, summary):
    hotspots = summary.get('hotspots', [])[:5]
    timeline = []
    for idx, item in enumerate(summary.get('alerts', [])[:6]):
        timeline.append({
            'slot': idx + 1,
            'title': item.get('title', 'Evento crítico'),
            'region': item.get('region', 'Global'),
            'level': item.get('level', 'orange'),
        })

    return {
        'headline': 'GLOBAL WAR MAP',
        'status': summary.get('global_label', 'MODERADO'),
        'primary_hotspot': hotspots[0]['region'] if hotspots else 'Global',
        'timeline': timeline,
        'layers': {
            'total_events': len(events or []),
            'critical_events': sum(1 for e in (events or []) if e.get('level') == 'red'),
            'elevated_events': sum(1 for e in (events or []) if e.get('level') == 'orange'),
        }
    }



def build_critical_news_data(limit=10):
    feed = safe_get_cache('intel_feed')
    if not feed:
        feed = build_intel_feed_data()
        safe_set_cache('intel_feed', feed)

    news = feed.get('news', [])
    ranked = []
    for idx, item in enumerate(news):
        text = f"{item.get('title', '')} {item.get('description', '')} {item.get('region', '')}"
        hits = classify_categories(text)
        level = item.get('level', 'green')
        base = 85 if level == 'red' else 68 if level == 'orange' else 54 if level == 'purple' else 38
        score = base
        score += hits.get('war', 0) * 10
        score += hits.get('military', 0) * 8
        score += hits.get('geopolitical', 0) * 6
        score += hits.get('infrastructure', 0) * 5
        score += hits.get('cyber', 0) * 5
        score += hits.get('seismic', 0) * 4
        score = max(1, min(99, score))
        slug = build_news_slug(item, idx)
        ranked.append({
            'title': item.get('title', 'Alerta crítico'),
            'description': item.get('description') or item.get('summary') or 'Evento de relevância estratégica em monitoramento ativo.',
            'region': item.get('region', 'Global'),
            'level': level,
            'link': f'/noticia/{slug}.html',
            'original_link': item.get('link', '#'),
            'tag': infer_critical_tag(item, hits),
            'score': score,
            'source': item.get('source', 'Fonte aberta'),
            'slug': slug,
            'context_hint': derive_news_intelligence({**item, 'tag': infer_critical_tag(item, hits)})['context'],
        })

    ranked.sort(key=lambda x: (-x['score'], x['title']))
    dynamic_items = ranked[:5]

    static_items = []
    for idx, item in enumerate(PROJECT_CRITICAL_REPORTS):
        clone = dict(item)
        original_file = clone.get('link', '')
        slug = build_news_slug(clone, idx + 100)
        clone['link'] = f'/noticia/{slug}.html'
        clone['slug'] = slug
        clone['source'] = 'Real Time Journal'
        clone['context_hint'] = derive_news_intelligence(clone)['context']
        if original_file in ANALYSIS_BY_FILE:
            clone['analysis_link'] = build_analysis_url(original_file)
            clone['source_link'] = build_analysis_url(original_file)
            clone['original_link'] = build_analysis_url(original_file)
        static_items.append(clone)

    top_items = ensure_critical_items(dynamic_items, static_items, limit=limit)
    return {
        'title': 'Top 10 agora',
        'intro': 'Matriz ampliada de relatórios e notícias críticas relevantes agora, combinando 5 alertas dinâmicos das fontes abertas com 5 relatórios estratégicos do próprio projeto, sempre com 10 entradas garantidas mesmo em modo de contingência.',
        'updated_at': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'items': top_items,
    }


# =========================
# CORE BUILDERS
# =========================
def build_intel_feed_data():
    news = fetch_all_news()

    events = []
    events.extend(fetch_earthquakes())
    for item in news[:10]:
        events.append(build_event_from_news_item(item))

    if len(events) < 3:
        events.extend(DEFAULT_EVENTS)

    return {
        'events': events[:18],
        'news': news[:16],
    }


def build_threat_summary_data():
    feed = safe_get_cache('intel_feed')
    if not feed:
        feed = build_intel_feed_data()
        safe_set_cache('intel_feed', feed)

    news = feed.get('news', [])
    events = feed.get('events', [])

    category_hits = Counter({key: 0 for key in CATEGORY_DEFINITIONS.keys()})
    hotspot_scores = defaultdict(int)
    count_map = {
        'military_alerts': 0,
        'war_detections': 0,
        'cyber_incidents': 0,
        'financial_crime_alerts': 0,
        'violent_crime_alerts': 0,
        'civil_unrest_alerts': 0,
    }

    for item in news:
        text = f"{item.get('title', '')} {item.get('description', '')} {item.get('region', '')}"
        hits = classify_categories(text)
        level = item.get('level', 'green')
        weight = 3 if level == 'red' else 2 if level == 'orange' else 2 if level == 'purple' else 1
        for key, value in hits.items():
            if value:
                category_hits[key] += value * weight
        region = item.get('region') or 'Global'
        hotspot_scores[region] += sum(hits.values()) * weight or weight
        count_map['military_alerts'] += 1 if level in ('red', 'orange') else 0
        count_map['war_detections'] += 1 if hits['war'] else 0
        count_map['cyber_incidents'] += 1 if hits['cyber'] else 0
        count_map['financial_crime_alerts'] += 1 if hits['financial_crime'] else 0
        count_map['violent_crime_alerts'] += 1 if hits['violent_crime'] else 0
        count_map['civil_unrest_alerts'] += 1 if hits['civil_unrest'] else 0

    seismic_events = 0
    for event in events:
        if event.get('title') == 'ALERTA SÍSMICO':
            category_hits['seismic'] += 4 if event.get('level') == 'red' else 2
            hotspot_scores[event.get('region') or 'Monitoramento Sísmico'] += 3
            seismic_events += 1

    total_signal = sum(category_hits.values())
    scores = {}
    for key in CATEGORY_DEFINITIONS.keys():
        share_component = ((category_hits[key] / total_signal) * 100) if total_signal else 0
        intensity_component = min(100, category_hits[key] * 9)
        value = round((share_component * 0.55) + (intensity_component * 0.45))
        if category_hits[key] > 0 and value == 0:
            value = 1
        scores[key] = value

    summary = {
        'global_level': 'moderate',
        'global_label': 'MODERADO',
        'defcon_label': 'Nível Amarelo',
        'message': 'Monitoramento ativo com foco em mudanças de padrão e novos gatilhos de ameaça.',
        'counts': {
            **count_map,
            'seismic_events': seismic_events,
        },
        'scores': scores,
        'trends': {key: '→' for key in CATEGORY_DEFINITIONS.keys()},
        'alerts': [
            {
                'title': n['title'],
                'time': 'LIVE',
                'region': n.get('region', 'Global'),
                'level': n.get('level', 'orange'),
                'link': n.get('link', '#'),
            }
            for n in news[:8]
        ],
        'hotspots': [
            {'region': region, 'score': min(99, int(score * 7)), 'reason': 'atividade crítica'}
            for region, score in sorted(hotspot_scores.items(), key=lambda x: x[1], reverse=True)[:6]
        ],
        'gemini_active': bool(model),
    }

    enriched = run_with_timeout(ai_enrich_summary, AI_TIMEOUT, news, summary) or summary

    stabilized_scores = {}
    trends = {}
    for key, raw_value in enriched.get('scores', {}).items():
        stabilized_scores[key], trends[key] = stabilize(key, raw_value)

    enriched['scores'] = stabilized_scores
    enriched['trends'] = trends

    war_score = stabilized_scores.get('war', 0)
    military_score = stabilized_scores.get('military', 0)
    geo_score = stabilized_scores.get('geopolitical', 0)

    predictive = {
        'war': predictive_analysis('war', stabilized_scores.get('war', 0)),
        'military': predictive_analysis('military', stabilized_scores.get('military', 0)),
        'geopolitical': predictive_analysis('geopolitical', stabilized_scores.get('geopolitical', 0)),
        'infrastructure': predictive_analysis('infrastructure', stabilized_scores.get('infrastructure', 0)),
        'cyber': predictive_analysis('cyber', stabilized_scores.get('cyber', 0)),
    }
    enriched['predictive'] = predictive
    enriched['early_warning'] = (
        check_early_warning(predictive.get('war')) or
        check_early_warning(predictive.get('military')) or
        check_early_warning(predictive.get('geopolitical'))
    )
    enriched['war_map'] = build_global_war_map_payload(events, enriched)

    if war_score >= 45 or military_score >= 48 or (war_score >= 35 and military_score >= 35):
        enriched['global_level'] = 'critical'
        enriched['global_label'] = 'CRÍTICO'
        enriched['defcon_label'] = 'Nível Vermelho'
        enriched['message'] = 'Sinais fortes de escalada militar, conflito ativo ou vetores de guerra em destaque nas fontes abertas.'
    elif war_score >= 25 or military_score >= 28 or geo_score >= 24:
        enriched['global_level'] = 'elevated'
        enriched['global_label'] = 'ELEVADO'
        enriched['defcon_label'] = 'Nível Laranja'
        enriched['message'] = 'Monitoramento reforçado para escalada regional, risco militar e instabilidade geopolítica.'
    else:
        enriched['global_level'] = 'moderate'
        enriched['global_label'] = 'MODERADO'
        enriched['defcon_label'] = 'Nível Amarelo'
        enriched['message'] = 'Monitoramento ativo com foco em mudanças de padrão e novos gatilhos de ameaça.'

    return enriched


# =========================
# STATIC + SEO ROUTES
# =========================
@app.route('/')
def home():
    return send_from_directory('.', 'index.html')


@app.route('/analise/<slug>')
@app.route('/analise/<slug>.html')
def analysis_page(slug):
    page = ANALYSIS_BY_SLUG.get(slug)
    file_path = page['file'] if page else os.path.join('analise', f'{slug}.html')
    if not os.path.exists(file_path):
        return send_from_directory('.', 'index.html'), 404
    raw_html = open(file_path, 'r', encoding='utf-8').read()
    title = page.get('title', slug) if page else slug.replace('-', ' ').title()
    description = page.get('description', 'Análise estratégica do Real Time Journal.') if page else 'Análise estratégica do Real Time Journal.'
    final_html = inject_seo_into_html(raw_html, request.url, title, description)
    return Response(final_html, mimetype='text/html; charset=utf-8')


@app.route('/noticia/<slug>')
@app.route('/noticia/<slug>.html')
def news_page(slug):
    payload = build_critical_news_data(limit=10)
    for item in payload.get('items', []):
        item_slug = item.get('slug')
        if not item_slug and str(item.get('link', '')).startswith('/noticia/'):
            item_slug = item['link'].split('/noticia/', 1)[1]
        if item_slug == slug:
            if item.get('analysis_link') is None:
                original_link = item.get('original_link') or item.get('source_link') or ''
                if original_link in ANALYSIS_BY_FILE:
                    item['analysis_link'] = build_analysis_url(original_link)
            return Response(render_news_page(item, slug), mimetype='text/html; charset=utf-8')
    fallback_file = os.path.join('noticia', f'{slug}.html')
    if os.path.exists(fallback_file):
        return send_from_directory('noticia', f'{slug}.html')
    return send_from_directory('.', 'index.html'), 404


@app.route('/<path:path>')
def static_files(path):
    if os.path.exists(path) and os.path.isfile(path):
        return send_from_directory('.', path)
    return send_from_directory('.', 'index.html')


# =========================
# API ROUTES
# =========================
@app.route('/intel-feed')
@app.route('/api/intel-feed')
def intel_feed():
    cached = safe_get_cache('intel_feed')
    if cached:
        return jsonify(cached)

    data = run_with_timeout(build_intel_feed_data, HTTP_TIMEOUT + 8)
    if not data:
        data = {'events': DEFAULT_EVENTS.copy(), 'news': DEFAULT_NEWS.copy()}

    safe_set_cache('intel_feed', data)
    return jsonify(data)


@app.route('/threat-summary')
@app.route('/api/threat-summary')
@app.route('/api/classificacao')
def threat_summary():
    cached = safe_get_cache('threat_summary')
    if cached:
        return jsonify(cached)

    data = run_with_timeout(build_threat_summary_data, AI_TIMEOUT + 6)
    if not data:
        data = {
            'global_level': 'elevated',
            'global_label': 'ELEVADO',
            'defcon_label': 'Nível Laranja',
            'message': 'Monitoramento reforçado para escalada regional, risco militar e instabilidade geopolítica.',
            'counts': {
                'military_alerts': 8,
                'war_detections': 4,
                'cyber_incidents': 5,
                'financial_crime_alerts': 6,
                'violent_crime_alerts': 7,
                'civil_unrest_alerts': 5,
                'seismic_events': 3,
            },
            'scores': {
                'war': 31,
                'military': 34,
                'geopolitical': 28,
                'seismic': 12,
                'infrastructure': 14,
                'cyber': 11,
                'financial_crime': 6,
                'violent_crime': 4,
                'civil_unrest': 5,
            },
            'trends': {
                'war': '↑',
                'military': '↑',
                'geopolitical': '→',
                'seismic': '→',
                'infrastructure': '↑',
                'cyber': '→',
                'financial_crime': '→',
                'violent_crime': '→',
                'civil_unrest': '→',
            },
            'predictive': {
                'war': {'current': 31, 'projected': 36, 'velocity': 2.0, 'trend': 'ESCALANDO'},
                'military': {'current': 34, 'projected': 39, 'velocity': 2.3, 'trend': 'ESCALANDO'},
                'geopolitical': {'current': 28, 'projected': 30, 'velocity': 1.0, 'trend': 'ESTÁVEL'},
                'infrastructure': {'current': 14, 'projected': 17, 'velocity': 1.4, 'trend': 'ESTÁVEL'},
                'cyber': {'current': 11, 'projected': 14, 'velocity': 1.2, 'trend': 'ESTÁVEL'}
            },
            'early_warning': None,
            'war_map': {
                'headline': 'GLOBAL WAR MAP',
                'status': 'ELEVADO',
                'primary_hotspot': 'Oriente Médio',
                'timeline': [],
                'layers': {'total_events': 6, 'critical_events': 2, 'elevated_events': 3}
            },
            'alerts': DEFAULT_NEWS[:5],
            'hotspots': [
                {'region': 'Oriente Médio', 'score': 93, 'reason': 'guerra / escalada militar'},
                {'region': 'Leste Europeu', 'score': 88, 'reason': 'conflito / pressão regional'},
            ],
            'gemini_active': bool(model),
        }

    safe_set_cache('threat_summary', data)
    return jsonify(data)


@app.route('/critical-news')
@app.route('/api/critical-news')
def critical_news():
    cached = safe_get_cache('critical_news')
    if cached:
        return jsonify(cached)

    data = run_with_timeout(build_critical_news_data, HTTP_TIMEOUT + 4)
    if not data:
        data = {
            'title': 'Top 10 agora',
            'intro': 'Matriz ampliada de relatórios e notícias críticas relevantes agora, combinando feed dinâmico e relatórios estratégicos do projeto.',
            'updated_at': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
            'items': [
                {
                    'title': item.get('title', 'Alerta crítico'),
                    'description': item.get('description', 'Evento de alta prioridade em monitoramento.'),
                    'region': item.get('region', 'Global'),
                    'level': item.get('level', 'orange'),
                    'link': item.get('link', '#'),
                    'tag': 'Geopolítica',
                    'score': 70,
                }
                for item in ensure_critical_items(DYNAMIC_CRITICAL_FALLBACK, PROJECT_CRITICAL_REPORTS, limit=10)
            ],
        }

    safe_set_cache('critical_news', data)
    return jsonify(data)


@app.route('/ask-ai', methods=['POST'])
@app.route('/api/ask-ai', methods=['POST'])
def ask_ai_route():
    payload = request.get_json(silent=True) or {}
    prompt = (payload.get('prompt') or payload.get('pergunta') or '').strip()

    if not prompt:
        return jsonify({'answer': 'Nenhuma pergunta foi enviada.'}), 400

    answer = run_with_timeout(ai_answer, AI_TIMEOUT, prompt)
    if not answer:
        answer = (
            'O sistema manteve continuidade operacional, mas a análise avançada excedeu o tempo limite. '
            'Tente uma pergunta mais curta ou consulte novamente em instantes.'
        )

    return jsonify({'answer': answer, 'gemini_active': bool(model)})


@app.route('/health')
@app.route('/api/health')
def health():
    return jsonify({
        'status': 'ok',
        'time': datetime.now(timezone.utc).isoformat(),
        'gemini_active': bool(model),
        'feeds': [feed['name'] for feed in RSS_FEEDS],
        'routes': ['/intel-feed', '/threat-summary', '/critical-news', '/ask-ai', '/api/intel-feed', '/api/threat-summary', '/api/critical-news', '/api/ask-ai'],
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
