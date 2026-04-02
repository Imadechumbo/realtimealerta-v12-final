import os, html
from pathlib import Path

ROOT = Path(__file__).resolve().parent

ANALYSIS_PAGES = [
    ('artigo3.html','uma-possivel-terceira-guerra-mundial','Uma Possível Terceira Guerra Mundial','Sinais, riscos e limites da escalada global em um cenário de tensão prolongada.'),
    ('artigo4.html','conflitos-modernos-e-o-novo-cenario-geopolitico','Conflitos Modernos e o Novo Cenário Geopolítico','Como guerras híbridas, drones e pressão regional remodelam o tabuleiro internacional.'),
    ('artigo5.html','infraestrutura-critica-na-geopolitica-moderna','Infraestrutura Crítica na Geopolítica Moderna','Como cabos, satélites, energia e logística moldam poder, resiliência e vulnerabilidade global.'),
    ('artigo6.html','economia-global-em-tempos-de-instabilidade','Economia Global em Tempos de Instabilidade','Pressão energética, cadeias logísticas e impactos econômicos em cenários de instabilidade geopolítica.'),
    ('artigo7.html','tecnologia-e-guerra-no-seculo-xxi','Tecnologia e Guerra no Século XXI','Drones, sensores, guerra eletrônica e a transformação tecnológica do campo de batalha.'),
    ('artigo8.html','cadeias-logisticas-globais-e-seguranca-internacional','Cadeias Logísticas Globais e Segurança Internacional','Rotas marítimas, gargalos e exposição sistêmica das cadeias globais.'),
    ('relatorio1.html','crise-dos-semicondutores','Relatório 01 • Crise dos Semicondutores','Sensibilidade geopolítica da cadeia tecnológica e efeitos estratégicos sobre indústria e defesa.'),
    ('relatorio2.html','cabos-submarinos-e-satelites','Relatório 02 • Cabos Submarinos e Satélites','Infraestrutura crítica da era digital, dependência global e riscos de interrupção.'),
    ('relatorio3.html','escudos-da-america','Relatório 03 • Escudos da América','Patriot, THAAD, Aegis, GMD e a arquitetura antimíssil dos Estados Unidos.'),
    ('relatorio4.html','ucrania-e-guerra-de-drones','Relatório 04 • Ucrânia e Guerra de Drones','Saturação, defesa aérea, custo de interceptação e mudança do equilíbrio operacional.'),
    ('relatorio5.html','hormuz-e-mar-vermelho','Relatório 05 • Hormuz e Mar Vermelho','Risco sistêmico para energia, seguros, frete e rotas alternativas.'),
    ('relatorio6.html','taiwan-e-mar-do-sul-da-china','Relatório 06 • Taiwan e Mar do Sul da China','Zona cinzenta, dissuasão e sinais graduais de escalada no Indo-Pacífico.'),
    ('relatorio7.html','infraestrutura-critica-e-ciberataques','Relatório 07 • Infraestrutura Crítica e Ciberataques','Hardening, superfície de ataque e leitura estratégica de ciberameaças.'),
    ('relatorio8.html','satelites-comerciais-e-osint-orbital','Relatório 08 • Satélites Comerciais e OSINT Orbital','O valor operacional das imagens comerciais e do monitoramento orbital.'),
    ('relatorio9.html','cabos-submarinos-e-resiliencia','Relatório 09 • Cabos Submarinos e Resiliência','99% do tráfego global, vulnerabilidades e resposta estatal.'),
    ('relatorio10.html','golden-dome-e-defesa-do-territorio','Relatório 10 • Golden Dome e Defesa do Território','Sensores hipersônicos, defesa em camadas e proteção do território.'),
    ('relatorio11.html','russia-china-e-coreia-do-norte','Relatório 11 • Rússia, China e Coreia do Norte','Eixo nuclear, dissuasão e vetores estratégicos contemporâneos.'),
]

NEWS_PAGES = [
    ('escudos-da-america-golden-dome-e-defesa-em-camadas','Escudos da América, Golden Dome e defesa em camadas','Leitura editorial sobre Patriot, THAAD, Aegis, GMD, sensores e a expansão da arquitetura antimíssil dos EUA.','relatorio3.html'),
    ('ucrania-drones-de-saturacao-e-evolucao-do-combate','Ucrânia, drones de saturação e evolução do combate','Panorama sobre UAVs, defesa aérea, profundidade operacional e mudança na relação custo-efeito do conflito.','relatorio4.html'),
    ('hormuz-mar-vermelho-e-risco-sistemico-para-comercio','Hormuz, Mar Vermelho e risco sistêmico para comércio','Impacto sobre energia, seguros, frete, rotas alternativas e exposição logística em corredores marítimos.','relatorio5.html'),
    ('taiwan-mar-do-sul-da-china-e-zona-cinzenta','Taiwan, Mar do Sul da China e zona cinzenta','Pressão militar, submarinos, radar de tiro, dissuasão e sinais graduais de escalada no Indo-Pacífico.','relatorio6.html'),
    ('hospitais-industria-e-ataque-digital-a-servicos-criticos','Hospitais, indústria e ataque digital a serviços críticos','Ciberameaças oportunistas, hardening e vulnerabilidades em saúde, logística, telecom e energia.','relatorio7.html'),
]

# Este arquivo documenta e regenera as URLs estáticas de /analise e /noticia.
print("Rotas estáticas já geradas em ./analise e ./noticia.")
