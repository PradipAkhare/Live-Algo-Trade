import streamlit as st
import pandas as pd
import requests
import pyotp
import math
import time
import matplotlib.pyplot as plt
from SmartApi import SmartConnect

# ==========================================
# 1. API CREDENTIALS (YAHAN APNI DETAILS DAALEIN)
# ==========================================
API_KEY = "A04oCs0I"
CLIENT_ID = "V551760"
PASSWORD = "2015" 
TOTP_SECRET = "4YILABJ5MTMUTRC45SUPNKANOU"

# ==========================================
# 2. CORE FUNCTIONS
# ==========================================

@st.cache_resource
def login_angel():
    smartApi = SmartConnect(api_key=API_KEY)
    try:
        totp = pyotp.TOTP(TOTP_SECRET).now()
        data = smartApi.generateSession(CLIENT_ID, PASSWORD, totp)
        if data['status']:
            return smartApi
    except Exception as e:
        pass
    return None

@st.cache_data(ttl=86400)
def get_instrument_df():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    response = requests.get(url)
    return pd.DataFrame(response.json())

def get_token_info(df, symbol, strike_price, option_type, expiry):
    filtered_df = df[(df['exch_seg'] == 'NFO') & 
                     (df['name'] == symbol) & 
                     (df['strike'] == str(float(strike_price) * 100)) & 
                     (df['symbol'].str.endswith(option_type)) & 
                     (df['expiry'] == expiry)]
    if not filtered_df.empty:
        return filtered_df.iloc[0]['token'], filtered_df.iloc[0]['symbol']
    return None, None

def place_exit_order(smartApi, symbol, token, qty, transaction_type="BUY"):
    try:
        orderparams = {
            "variety": "NORMAL",
            "tradingsymbol": symbol,
            "symboltoken": token,
            "transactiontype": transaction_type, 
            "exchange": "NFO",
            "ordertype": "MARKET",
            "producttype": "CARRYFORWARD", 
            "duration": "DAY",
            "quantity": qty
        }
        orderId = smartApi.placeOrder(orderparams)
        return orderId
    except Exception as e:
        return f"Error: {e}"

def black_scholes_greeks(S, K, T_days, opt_type="CE", r=0.10, v=0.15):
    T = max(T_days / 365.0, 0.001) 
    d1 = (math.log(S / K) + (r + 0.5 * v**2) * T) / (v * math.sqrt(T))
    d2 = d1 - v * math.sqrt(T)
    
    def cdf(x): return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0
    def pdf(x): return math.exp(-0.5 * x**2) / math.sqrt(2 * math.pi)
    
    if opt_type == "CE":
        delta = cdf(d1)
        theta = -(S * pdf(d1) * v) / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * cdf(d2)
    else:
        delta = cdf(d1) - 1
        theta = -(S * pdf(d1) * v) / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * cdf(-d2)
        
    vega = (S * pdf(d1) * math.sqrt(T)) / 100
    return round(delta, 2), round(theta / 365, 2), round(vega, 2)

# ==========================================
# 3. APP INITIALIZATION
# ==========================================

st.title("🚀 SmartOptions Builder (Sensibull Clone)")

smartApi = login_angel()
if smartApi is None:
    st.error("Login Failed ❌ Kripya API Key, PIN aur TOTP check karein.")
    st.stop()

st.sidebar.success("✅ Angel One Login Successful!")
df = get_instrument_df()

# ==========================================
# 4. SIDEBAR SETTINGS
# ==========================================
st.sidebar.header("⚙️ Algo Settings")
target_strike = st.sidebar.number_input("Strike Price", value=25000, step=50)
target_expiry = st.sidebar.text_input("Expiry Date (e.g. 29DEC2026)", value="29DEC2026")
lot_size = st.sidebar.number_input("Lot Size", value=25)
target_profit = st.sidebar.number_input("Target Profit (₹)", value=1000)
max_loss = st.sidebar.number_input("Max Loss (₹)", value=-500)
days_to_expiry = st.sidebar.number_input("Days to Expiry", value=3)

start_algo = st.sidebar.button("▶️ START LIVE ALGO")

# ==========================================
# 5. MAIN DASHBOARD LOGIC
# ==========================================
if start_algo:
    ce_token, ce_symbol = get_token_info(df, "NIFTY", target_strike, "CE", target_expiry)
    pe_token, pe_symbol = get_token_info(df, "NIFTY", target_strike, "PE", target_expiry)
    
    if ce_token and pe_token:
        # Initial Prices Fetch
        ce_data = smartApi.ltpData("NFO", ce_symbol, ce_token)
        pe_data = smartApi.ltpData("NFO", pe_symbol, pe_token)
        
        entry_ce = ce_data['data']['ltp']
        entry_pe = pe_data['data']['ltp']
        entry_prem = entry_ce + entry_pe
        
        st.success(f"✅ Strategy Executed! CE Token: {ce_token} | PE Token: {pe_token}")
        st.info(f"Total Premium Collected: ₹{round(entry_prem, 2)}")
        
        # --- GRAPH DRAW ---
        st.subheader("📉 Expiry Payoff Graph (Short Straddle)")
        prices = range(int(target_strike) - 1000, int(target_strike) + 1000, 10)
        pnl_list = []
        for p in prices:
            ce_pnl = entry_ce - max(0, p - target_strike)
            pe_pnl = entry_pe - max(0, target_strike - p)
            pnl_list.append((ce_pnl + pe_pnl) * lot_size)
            
        fig, ax = plt.subplots(figsize=(10,4))
        ax.plot(prices, pnl_list, color='blue', linewidth=2)
        ax.axhline(0, color='black', linestyle='--')
        ax.axvline(target_strike, color='gray', linestyle=':', label="Strike")
        ax.fill_between(prices, pnl_list, 0, where=[p >= 0 for p in pnl_list], color='green', alpha=0.3)
        ax.fill_between(prices, pnl_list, 0, where=[p < 0 for p in pnl_list], color='red', alpha=0.3)
        ax.set_xlabel("Nifty Price")
        ax.set_ylabel("P&L (₹)")
        st.pyplot(fig)
        
        # --- LIVE P&L TRACKER UI ---
        st.markdown("---")
        st.subheader("⚡ Live MTM & Option Greeks")
        
        col1, col2, col3 = st.columns(3)
        ce_metric = col1.empty() 
        pe_metric = col2.empty()
        pnl_metric = col3.empty()
        
        g_col1, g_col2, g_col3 = st.columns(3)
        delta_metric = g_col1.empty()
        theta_metric = g_col2.empty()
        vega_metric = g_col3.empty()
        
        status_msg = st.empty()
        stop_algo = st.button("🛑 STOP ALGO")
        
        # Live Loop
        while not stop_algo:
            try:
                live_ce = smartApi.ltpData("NFO", ce_symbol, ce_token)['data']['ltp']
                live_pe = smartApi.ltpData("NFO", pe_symbol, pe_token)['data']['ltp']
                live_prem = live_ce + live_pe
                pnl = (entry_prem - live_prem) * lot_size
                
                # Greeks Calculate (Assuming Spot == Target Strike for simple visualization)
                ce_delta, ce_theta, ce_vega = black_scholes_greeks(target_strike, target_strike, days_to_expiry, "CE")
                pe_delta, pe_theta, pe_vega = black_scholes_greeks(target_strike, target_strike, days_to_expiry, "PE")
                
                total_delta = ce_delta + pe_delta
                total_theta = ce_theta + pe_theta
                total_vega = ce_vega + pe_vega
                
                # Update UI Metrics
                ce_metric.metric(label=f"Call ({ce_symbol})", value=f"₹ {live_ce}")
                pe_metric.metric(label=f"Put ({pe_symbol})", value=f"₹ {live_pe}")
                pnl_metric.metric(label="Total MTM P&L", value=f"₹ {round(pnl, 2)}", delta=round(pnl, 2))
                
                delta_metric.metric(label="Total Delta", value=round(total_delta, 2))
                theta_metric.metric(label="Total Theta (Decay)", value=f"₹ {round(total_theta * lot_size, 2)} / day")
                vega_metric.metric(label="Total Vega", value=round(total_vega, 2))
                
                # Auto Exit Logic
                if pnl >= target_profit:
                    status_msg.success(f"🎉 TARGET HIT! (+₹{round(pnl,2)}) Auto-squaring off...")
                    place_exit_order(smartApi, ce_symbol, ce_token, lot_size) 
                    place_exit_order(smartApi, pe_symbol, pe_token, lot_size) 
                    st.balloons() 
                    break
                    
                elif pnl <= max_loss:
                    status_msg.error(f"⚠️ STOP LOSS HIT! (-₹{abs(round(pnl,2))}) Auto-squaring off...")
                    place_exit_order(smartApi, ce_symbol, ce_token, lot_size)
                    place_exit_order(smartApi, pe_symbol, pe_token, lot_size)
                    break
                    
                time.sleep(1) # Angel One rate limit respect karne ke liye 1 second delay
            
            except Exception as e:
                st.warning(f"Live data fetch error: {e}")
                time.sleep(2)
            
    else:
        st.error(f"❌ NIFTY {target_strike} CE/PE for expiry {target_expiry} nahi mila. Kripya details check karein.")
