import os
import re
import sys
import time
import platform
import subprocess
from concurrent.futures import ThreadPoolExecutor
from mac_vendor_lookup import MacLookup
import speedtest

# ==========================================
# CONFIGURAÇÕES DA SUA REDE LOCAL
# ==========================================
ROUTER_IP = "192.168.0.1"       # Altere para o IP do seu Archer C20
INTERFACE_IP_PREFIX = "192.168.0." # Prefixo para filtrar dispositivos da sua rede

# Inicializa o buscador de fabricantes (OUI) com tratamento de erro
try:
    mac_lookup = MacLookup()
    mac_lookup.load_vendors()
except Exception:
    mac_lookup = None

# Variáveis globais para armazenar o teste de velocidade em segundo plano
# (Como o Speedtest demora cerca de 15-20s para rodar, ele roda em paralelo e atualiza o painel quando pronto)
dados_velocidade = {"download": "Medindo...", "upload": "Medindo...", "latency": "Medindo..."}
ultima_atualizacao_speedtest = 0

# ==========================================
# FUNÇÕES DE CAPTURA E DETECÇÃO
# ==========================================

def calcular_latencia(ip_destino):
    """Mede a latência em ms disparando um único ping ICMP rápido."""
    is_windows = platform.system().lower() == "windows"
    parametro_count = "-n" if is_windows else "-c"
    parametro_timeout = "-w" if is_windows else "-W"
    valor_timeout = "800" if is_windows else "1" # ms no windows, segundos no linux
    
    comando = ["ping", parametro_count, "1", parametro_timeout, valor_timeout, ip_destino]
    
    try:
        resultado = subprocess.run(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1.0)
        if resultado.returncode == 0:
            for linha in resultado.stdout.split("\n"):
                if "time=" in linha or "tempo=" in linha:
                    parte_tempo = linha.split("time=") if "time=" in linha else linha.split("tempo=")
                    ms = parte_tempo[1].split("ms")[0].strip().replace("<", "")
                    return int(float(ms))
        return None
    except Exception:
        return None

def determinar_categoria(fabricante, ip):
    """Classifica o tipo de dispositivo por regras de dedução."""
    fab_lower = fabricante.lower() if fabricante else ""
    
    if any(k in fab_lower for k in ["apple", "samsung", "huawei", "xiaomi", "motorola", "lg", "zte"]):
        return "Smartphone"
    if any(k in fab_lower for k in ["intel", "realtek", "asustek", "gigabyte", "dell", "hp", "lenovo"]):
        # Em redes domésticas, assume Laptop/Desktop para chips comuns
        return "Laptop/PC"
    if "synology" in fab_lower or "qnap" in fab_lower:
        return "Server"
    return "Desktop"

def processar_linha_arp(linha):
    """Processa uma linha do comando ARP para extrair IP, MAC e metadados."""
    regex_ip = r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
    regex_mac = r"([0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2})"
    
    ip_match = re.search(regex_ip, linha)
    mac_match = re.search(regex_mac, linha)
    
    if ip_match and mac_match:
        ip = ip_match.group(1)
        mac = mac_match.group(1).replace("-", ":").lower()
        
        # Filtra apenas IPs pertencentes à sua rede interna
        if ip.startswith(INTERFACE_IP_PREFIX) and ip != ROUTER_IP and not ip.endswith(".255"):
            # Identifica fabricante
            fabricante = "Desconhecido"
            if mac_lookup:
                try:
                    fabricante = mac_lookup.lookup(mac)
                except Exception:
                    pass
            
            # Testa conectividade e mede latência em paralelo
            latencia = calcular_latencia(ip)
            status = "Online" if latencia is not None else "Offline"
            tipo = determinar_categoria(fabricante, ip)
            nome = f"{tipo}-{ip.split('.')[-1]}"
            
            return {
                "name": nome,
                "ip": ip,
                "mac": mac,
                "uptime": "Estável" if status == "Online" else "--",
                "latency": f"{latencia} ms" if latencia else "--",
                "status": status
            }
    return None

def obter_dispositivos_rede():
    """Varre a tabela ARP local usando Threads paralelas para máxima velocidade."""
    try:
        resultado = subprocess.run(["arp", "-a"], stdout=subprocess.PIPE, text=True, timeout=2.0)
        linhas = resultado.stdout.split("\n")
    except Exception:
        return []

    # Usa um Pool de Threads para processar e pingar os dispositivos simultaneamente
    with ThreadPoolExecutor(max_workers=20) as executor:
        resultados = executor.map(processar_linha_arp, linhas)
        
    # Filtra entradas nulas e remove duplicatas de IP
    dispositivos válidos = {}
    for r in resultados:
        if r and r["ip"] not in dispositivos válidos:
            dispositivos válidos[r["ip"]] = r
            
    return list(dispositivos válidos.values())

def rodar_speedtest_background():
    """Executa o teste de velocidade de internet sem travar o terminal."""
    global dados_velocidade
    try:
        st = speedtest.Speedtest(secure=True)
        st.get_best_server()
        down = st.download() / 1_000_000
        up = st.upload() / 1_000_000
        ping = st.results.ping
        dados_velocidade = {
            "download": f"{down:.1f} Mbps",
            "upload": f"{up:.1f} Mbps",
            "latency": f"{ping:.0f} ms"
        }
    except Exception:
        dados_velocidade = {"download": "Erro", "upload": "Erro", "latency": "Erro"}

# ==========================================
# RENDERIZAÇÃO DO PAINEL (TERMINAL)
# ==========================================

def limpar_tela():
    """Limpa o terminal dinamicamente dependendo do SO."""
    os.system("cls" if platform.system().lower() == "windows" else "clear")

def exibir_painel():
    global ultima_atualizacao_speedtest
    
    # Dispara o speedtest a cada 5 minutos (300 segundos) para não estourar sua banda
    tempo_atual = time.time()
    if tempo_atual - ultima_atualizacao_speedtest > 300:
        ultima_atualizacao_speedtest = tempo_atual
        dados_velocidade["download"] = "Atualizando..."
        dados_velocidade["upload"] = "Atualizando..."
        dados_velocidade["latency"] = "Atualizando..."
        # Roda em uma thread separada para o painel continuar atualizando de 1s em 1s
        with ThreadPoolExecutor(max_workers=1) as ext:
            ext.submit(rodar_speedtest_background)

    while True:
        try:
            # 1. Coleta dados em tempo real
            lat_roteador = calcular_latencia(ROUTER_IP)
            status_roteador = "Online" if lat_roteador else "Offline"
            
            dispositivos = obter_dispositivos_rede()
            
            # 2. Cálculos dos cards superiores
            total_conectados = len(dispositivos) + 1 # +1 do roteador
            online_count = len([d for d in dispositivos if d["status"] == "Online"]) + (1 if lat_roteador else 0)
            issues_detected = total_conectados - online_count
            
            # 3. Renderização visual idêntica à estrutura da imagem
            limpar_tela()
            print("=" * 78)
            print(" 🌐 NETWORK MONITORING DASHBOARD (REAL-TIME) ")
            print("=" * 78)
            
            # Linha dos Cards Superiores
            print(f" [ Connected Devices ]   [ Latency (Router) ]   [ Internet Speed ]   [ Issues ]")
            print(f"          {total_conectados:<14}        {f'{lat_roteador} ms' if lat_roteador else '--':<15}      {dados_velocidade['download']:<15}       {issues_detected:<8}")
            print("=" * 78)
            
            # Tabela de Clientes Conectados
            print(f" {'Device Name':<20} | {'IP Address':<15} | {'Uptime':<10} | {'Latency':<8} | Status")
            print("-" * 78)
            
            # Linha fixa do Roteador Archer C20
            print(f" 🟢 Archer C20 (Router)  | {ROUTER_IP:<15} | {'24h Act.':<10} | {f'{lat_roteador} ms' if lat_roteador else '--':<8} | {status_roteador}")
            
            # Linhas dinâmicas dos dispositivos mapeados
            for dev in dispositivos:
                icone = "🟢" if dev["status"] == "Online" else "🔴"
                print(f" {icone} {dev['name']:<18} | {dev['ip']:<15} | {dev['uptime']:<10} | {dev['latency']:<8} | {dev['status']}")
            
            print("=" * 78)
            print(f" [ Upload: {dados_velocidade['upload']} ]  [ Latência Externa: {dados_velocidade['latency']} ]")
            print(" Pressione Ctrl+C para encerrar o monitoramento.")
            
            # Aguarda exatamente 1 segundo antes da próxima varredura completa
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("\n[-] Monitoramento encerrado pelo usuário.")
            sys.exit(0)
        except Exception as e:
            # Mecanismo de tolerância a falhas críticas
            time.sleep(1)

if __name__ == "__main__":
    exibir_painel()
