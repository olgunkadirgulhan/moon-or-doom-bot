"""EMA50/200, RSI14, ATR14, hacim ortalaması."""
import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema50"] = EMAIndicator(df["Close"], 50).ema_indicator()
    df["ema200"] = EMAIndicator(df["Close"], 200).ema_indicator()
    df["rsi14"] = RSIIndicator(df["Close"], 14).rsi()
    atr = AverageTrueRange(df["High"], df["Low"], df["Close"], 14).average_true_range()
    # ta, ilk pencerede 0 döndürür; onu NaN yap ki hesaplara karışmasın
    df["atr14"] = atr.replace(0, np.nan)
    df["vol_ma20"] = df["Volume"].rolling(20).mean()
    return df


def last_atr(df: pd.DataFrame) -> float:
    atr = df["atr14"].dropna()
    if len(atr):
        return float(atr.iloc[-1])
    return float((df["High"] - df["Low"]).tail(14).mean())
