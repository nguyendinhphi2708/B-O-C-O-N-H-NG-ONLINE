import os
import json
import re
import time
import requests
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ID file Google Sheets
SPREADSHEET_ID = "12VZllfXfu4R-CuIfY8Vk5-ISS0nZVft8bLIwPq5DKkE"

CATE_LIST = [
    {"url_path": "sua-bot-cho-be", "cate_id": 99, "category_name": "Sữa bột"},
    {"url_path": "sua-pha-san-cho-be", "cate_id": 100, "category_name": "Sữa pha sẵn"}
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

def fetch_category_data(session, cate):
    # Sử dụng Web API công khai chuẩn website AVAKids
    api_url = "https://www.avakids.com/Category/GetProductCategory"
    
    headers = {
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Origin': 'https://www.avakids.com',
        'Referer': f'https://www.avakids.com/{cate["url_path"]}',
        'Sec-Ch-Ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest'
    }

    # Giả lập payload phân trang lấy nhiều sản phẩm
    payload = {
        'key': '',
        'category': cate['cate_id'],
        'page': 0,
        'pagesize': 200,
        'province': 1027,
        'sort': 0
    }

    # Thử gọi API chính thức
    try:
        response = session.post(api_url, headers=headers, data=payload, timeout=20)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict):
                return data.get('data', {}).get('products', []) or data.get('products', []) or data.get('listProducts', [])
            elif isinstance(data, list):
                return data
    except Exception as e:
        print(f"[-] Endpoint web 1 thử nghiệm lỗi: {e}")

    # Kênh dự phòng 2: Gateway với giả lập đầy đủ header trình duyệt
    gw_url = "https://api.avakids.com/gw/bus-ava-tmdt/api/Cate/GetproductCateV2"
    gw_headers = {
        'accept': 'application/json, text/plain, */*',
        'content-type': 'application/json',
        'origin': 'https://www.avakids.com',
        'os': 'WebAVAKids',
        'platform': '1',
        'provinceid': '1027',
        'referer': f'https://www.avakids.com/{cate["url_path"]}',
        'siteid': '17',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    }
    gw_payload = {
        "pageIndex": 0,
        "pageSize": 500,
        "provinceId": 1027,
        "urlCate": f"/{cate['url_path']}",
        "cateId": str(cate["cate_id"]),
        "filters": [{"filterId": 1, "filterTypeId": 6, "sortName": "FEATURED_PRODUCTS", "url": ""}]
    }

    res_gw = session.post(gw_url, headers=gw_headers, json=gw_payload, timeout=20)
    if res_gw.status_code == 200:
        return res_gw.json().get('data', {}).get('products', [])
    return []

def main():
    session = requests.Session()
    # Tải trước trang chủ để lấy cookie hợp lệ tránh WAF ngắt kết nối
    try:
        session.get("https://www.avakids.com", headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        }, timeout=15)
    except Exception:
        pass

    all_rows = []
    seen = set()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for cate in CATE_LIST:
        print(f"[*] Đang lấy dữ liệu ngành: {cate['category_name']}...")
        products = []
        try:
            products = fetch_category_data(session, cate)
            print(f"[+] Tìm thấy {len(products)} sản phẩm cho {cate['category_name']}")
        except Exception as e:
            print(f"Lỗi lấy ngành {cate['category_name']}: {e}")

        for p in products:
            p_code = p.get('productCode') or p.get('productPEId') or p.get('productId') or ""
            p_name = p.get('name') or p.get('productName') or ""
            if not p_code or not p_name or p_code in seen:
                continue
            seen.add(p_code)

            p_prices = p.get('productPrices', [{}])[0] if p.get('productPrices') else {}
            sale_price = clean_price(p_prices.get('price') or p.get('price') or 0)
            orig_price = clean_price(p_prices.get('originalPrice') or p_prices.get('hisPrice') or p.get('originalPrice') or sale_price)
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
            img_url = p.get('avatar') or p.get('picture') or ""
            if img_url and not img_url.startswith("http"):
                img_url = f"https://cdn.avakids.com{img_url}"
            prod_url = f"https://www.avakids.com{p.get('url', '')}" if p.get('url') else ""
            age = extract_target_age(p_name)

            all_rows.append([
                p_code, "", p_name, brand, cate["category_name"], age,
                orig_price, sale_price, promo_str, short_desc, detail_desc, "",
                img_url, prod_url, now_str
            ])
        time.sleep(2)

    if all_rows:
        print(f"[*] Đang kết nối Google Sheets và ghi {len(all_rows)} sản phẩm...")
        service_account_info = json.loads(os.environ["GCP_SA_KEY"])
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
        client = gspread.authorize(creds)

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
