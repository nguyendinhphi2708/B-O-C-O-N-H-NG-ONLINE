import os
import json
import re
import requests
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ID file Google Sheets của bạn
SPREADSHEET_ID = "12VZllfXfu4R-CuIfY8Vk5-ISS0nZVft8bLIwPq5DKkE"

CATE_LIST = [
    {"url_path": "/sua-bot-cho-be", "cate_id": 99, "category_name": "Sữa bột"},
    {"url_path": "/sua-pha-san-cho-be", "cate_id": 100, "category_name": "Sữa pha sẵn"}
]

def clean_price(price_val):
    if not price_val:
        return 0
    if isinstance(price_val, (int, float)):
        return int(price_val)
    nums = re.findall(r'\d+', str(price_val).replace('.', '').replace(',', ''))
    return int(nums[0]) if nums else 0

def clean_html(raw_html):
    if not raw_html:
        return ""
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', ' ', str(raw_html))).strip()

def extract_target_age(name):
    lower = name.lower()
    if any(x in lower for x in ['0-6', '0 - 6', 'số 1', 'so 1', 'infant', 'newborn']):
        return "0 - 6 tháng"
    if any(x in lower for x in ['6-12', '6 - 12', 'số 2', 'so 2']):
        return "6 - 12 tháng"
    if any(x in lower for x in ['1-2', '1 - 2', '1-3', '1 - 3', 'số 3', 'so 3', 'toddler']):
        return "1 - 3 tuổi"
    if any(x in lower for x in ['2-6', '2 - 6', 'số 4', 'so 4', 'kids', '3-10']):
        return "Trên 2 tuổi"
    return "Tất cả độ tuổi"

def main():
    url = "https://api.avakids.com/gw/bus-ava-tmdt/api/Cate/GetproductCateV2"
    headers = {
        'content-type': 'application/json',
        'provinceid': '1027',
        'siteid': '17',
        'os': 'WebAVAKids',
        'platform': '1',
        'accept': 'application/json, text/plain, */*',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    all_rows = []
    seen = set()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for cate in CATE_LIST:
        print(f"[*] Đang lấy dữ liệu ngành: {cate['category_name']}...")
        payload = {
            "pageIndex": 0,
            "pageSize": 1000,
            "provinceId": 1027,
            "urlCate": cate["url_path"],
            "cateId": str(cate["cate_id"]),
            "filters": [{"filterId": 1, "filterTypeId": 6, "sortName": "FEATURED_PRODUCTS", "url": ""}]
        }
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=30)
            if res.status_code == 200:
                products = res.json().get('data', {}).get('products', [])
                for p in products:
                    p_code = p.get('productCode') or p.get('productPEId') or ""
                    p_name = p.get('name') or ""
                    if not p_code or not p_name or p_code in seen:
                        continue
                    seen.add(p_code)

                    p_prices = p.get('productPrices', [{}])[0] if p.get('productPrices') else {}
                    sale_price = clean_price(p_prices.get('price', 0))
                    orig_price = clean_price(p_prices.get('originalPrice') or p_prices.get('hisPrice') or sale_price)
                    if orig_price == 0:
                        orig_price = sale_price

                    promos = []
                    if p.get('gift', {}).get('name'):
                        promos.append(f"Tặng: {p['gift']['name']}")
                    if p.get('lstTextPromotion'):
                        for tp in p['lstTextPromotion']:
                            for b in tp.get('lstBlockTextPromotion', []):
                                for html_t in b.get('subTitle', []):
                                    txt = clean_html(html_t)
                                    if txt: promos.append(txt)
                    promo_str = " | ".join(promos)

                    short_desc = clean_html(p.get('shortDescription') or "")
                    detail_desc = clean_html(p.get('description') or short_desc)
                    brand = p.get('brandName') or ""
                    img_url = p.get('avatar') or ""
                    if img_url and not img_url.startswith("http"):
                        img_url = f"https://cdn.avakids.com{img_url}"
                    prod_url = f"https://www.avakids.com{p.get('url', '')}" if p.get('url') else ""
                    age = extract_target_age(p_name)

                    all_rows.append([
                        p_code, "", p_name, brand, cate["category_name"], age,
                        orig_price, sale_price, promo_str, short_desc, detail_desc, "",
                        img_url, prod_url, now_str
                    ])
        except Exception as e:
            print(f"Lỗi cate {cate['category_name']}: {e}")

    if all_rows:
        print(f"[*] Đang kết nối Google Sheets và ghi {len(all_rows)} sản phẩm...")
        service_account_info = json.loads(os.environ["GCP_SA_KEY"])
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
        client = gspread.authorize(creds)

        # Tự động lấy tab tính đầu tiên trong bảng tính Google Sheets
        sheet = client.open_by_key(SPREADSHEET_ID).get_worksheet(0)
        headers = [
            "product_id", "barcode", "product_name", "brand", "category", "target_age",
            "original_price", "sale_price", "promo_text", "short_description",
            "detail_description", "preparation_guide", "image_url", "product_url", "updated_at"
        ]
        sheet.clear()
        sheet.update(range_name='A1', values=[headers] + all_rows)
        print(f"🎉 Đã cập nhật thành công {len(all_rows)} sản phẩm lên Google Sheet!")
    else:
        print("[!] Không lấy được sản phẩm nào.")

if __name__ == "__main__":
    main()
