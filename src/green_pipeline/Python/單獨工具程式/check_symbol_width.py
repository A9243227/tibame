import unicodedata

# 這個對照表用來把 Python 回傳的 East Asian Width 代碼轉成中文說明。
# F / W：通常代表全形或寬字元，例如「（」、「：」、「／」
# H / Na：通常代表半形或窄字元，例如 "("、":"、"/"
# N / A：不明顯屬於全形或半形的字元，先歸類成「其他」
SYMBOL_TYPES = {
    "F": "全形",
    "W": "全形",
    "H": "半形",
    "Na": "半形",
    "N": "其他",
    "A": "其他",
}

def check_char_width(char):
    """
    檢查單一字元是全形、半形或其他。

    範例：
    check_char_width("（") 會回傳 "全形"
    check_char_width("(") 會回傳 "半形"
    """
    if len(char) != 1:
        raise ValueError("check_char_width() 一次只能檢查一個字元")

    # unicodedata.east_asian_width() 會回傳 F、W、H、Na、N、A 這幾種代碼。
    width_code = unicodedata.east_asian_width(char)
    return SYMBOL_TYPES.get(width_code, "其他")

def is_symbol(char):
    """
    判斷單一字元是不是符號或標點。

    Python 的 unicode category 中：
    P 開頭代表 punctuation（標點）
    S 開頭代表 symbol（符號）
    """
    if len(char) != 1:
        raise ValueError("is_symbol() 一次只能檢查一個字元")

    category = unicodedata.category(char)
    return category.startswith("P") or category.startswith("S")

def check_symbols_in_text(text):
    """
    找出文字中的符號，並標示每個符號是全形、半形或其他。

    回傳格式是一個 list，每個符號會包含：
    symbol：原始符號
    width：全形 / 半形 / 其他
    unicode：Unicode 編碼，方便追查字元
    name：Unicode 官方名稱，方便確認符號種類
    """
    results = []
    for char in str(text):
        # 只檢查符號與標點，中文字、英文字、數字會先略過。
        if is_symbol(char):
            results.append({
                "symbol": char,
                "width": check_char_width(char),
                "unicode": f"U+{ord(char):04X}",
                "name": unicodedata.name(char, "UNKNOWN"),
            })
    return results

if __name__ == "__main__":
    # 直接執行這支檔案時，會用下面這段範例文字做測試。
    # 爬蟲組員可以先修改 sample_text，確認抓下來的文字有哪些全形/半形符號。
    sample_text = "台電（T-REC）, 憑證編號：ABC-001／2026"
    for item in check_symbols_in_text(sample_text):
        print(item)
