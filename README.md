# 🤖 Bot de Mercados Financieros para Telegram

Bot de Telegram que responde a comandos `/TICKER` con información completa y en tiempo real de cualquier activo financiero: acciones, criptos, forex, commodities, ETFs y bonos.

---

## 📁 Estructura del proyecto

```
telegram-bot/
├── bot.py           # Lógica principal del bot
├── market_data.py   # Obtención de datos y cálculo de indicadores
├── requirements.txt # Dependencias Python
├── .env.example     # Ejemplo de variables de entorno
└── README.md
```

---

## ⚙️ Instalación paso a paso

### 1. Requisitos previos
- Python 3.10 o superior
- pip actualizado

### 2. Clonar / descargar los archivos
Ponelos todos en una carpeta, por ejemplo `telegram-bot/`.

### 3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4. Configurar el token

**Opción A — Variable de entorno (recomendado):**
```bash
export TELEGRAM_TOKEN="TU_TOKEN_AQUI"
```

**Opción B — Editar bot.py directamente:**
```python
TELEGRAM_TOKEN = "TU_TOKEN_AQUI"
```

### 5. Ejecutar el bot
```bash
python bot.py
```

---

## 🚀 Uso del bot

| Comando | Activo |
|---------|--------|
| `/AAPL` | Apple Inc. (acción) |
| `/MSFT` | Microsoft (acción) |
| `/BTC` | Bitcoin (cripto) — se convierte automáticamente a BTC-USD |
| `/ETH` | Ethereum |
| `/EURUSD=X` | EUR/USD (forex) |
| `/GC=F` | Oro (commodity) |
| `/CL=F` | Petróleo WTI |
| `/SPY` | S&P 500 ETF |
| `/TLT` | Bono del Tesoro EEUU 20Y |
| `/^MERV` | Merval (índice argentino) |

---

## 📊 Información que muestra

- 💵 **Precio actual** en tiempo real
- 📈 **Variación %** del día con emoji verde/rojo
- 📈📉 **Máximo y mínimo** del día
- 🔢 **Volumen** actual y promedio
- 💰 **Market Cap** formateado (B, T, M)
- 📐 **RSI (14)** con señal de sobrecompra/sobreventa
- 📉 **MACD** con línea, señal, histograma y tendencia
- 📏 **EMA 200 y EMA 50** con señal alcista/bajista
- 🏷 **Tipo de activo** (Acción, Cripto, ETF, Forex, etc.)

---

## 🌐 Fuente de datos

Todos los datos provienen de **Yahoo Finance** via la librería `yfinance`. Los indicadores técnicos (RSI, MACD, EMA) se calculan localmente con los últimos 12 meses de datos históricos.

---

## ☁️ Deploy en servidor (opcional)

Para correrlo 24/7, podés usar:
- **Railway.app** (gratis, fácil): subí los archivos y agregá la variable `TELEGRAM_TOKEN` en Settings → Variables.
- **Render.com**: similar a Railway.
- **VPS propio**: usá `screen` o `systemd` para mantenerlo corriendo.

### Ejemplo con Railway:
1. Creá cuenta en railway.app
2. "New Project" → "Deploy from GitHub" o subí los archivos
3. En Variables, agregá: `TELEGRAM_TOKEN = tu_token`
4. Listo — el bot corre 24/7

---

## 🛠 Personalización

### Agregar más criptos con alias automático
En `market_data.py`, en el diccionario `crypto_aliases`:
```python
"PEPE": "PEPE-USD",
"WIF": "WIF-USD",
```

### Cambiar el período del RSI o EMAs
En `market_data.py`:
```python
rsi = calc_rsi(close, period=14)   # Cambiar a 7 o 21
ema200 = calc_ema(close, 200)      # Agregar EMA 50, 100, etc.
```

---

## ❓ Troubleshooting

| Error | Solución |
|-------|----------|
| `No se encontró el ticker` | Verificá el símbolo en finance.yahoo.com |
| `ModuleNotFoundError` | Corré `pip install -r requirements.txt` |
| Bot no responde | Verificá que el token sea correcto |
| Crypto no encontrada | Usá formato `BTC-USD`, `ETH-USD` en vez de solo `BTC` |
