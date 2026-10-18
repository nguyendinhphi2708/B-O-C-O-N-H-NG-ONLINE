import os
import json
import re
import time
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

SPREADSHEET_ID = "12VZllfXfu4R-CuIfY8Vk5-ISS0nZVft8bLIwPq5DKkE"

CATE_LIST = [
    {"url": "https://www.avakids.com/sua-bot-cho-be", "cate_id": "99", "name": "Sữa bột"},
    {"url": "https://www.avakids.com/sua-pha-san-cho-be", "cate_id": "100", "name": "Sữa pha sẵn"}
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
    all_rows = []
    seen = set()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768}
        )
        page = context.new_page()

        for cate in CATE_LIST:
            print(f"[*] Đang tải trang ngành: {cate['name']}...")
            try:
                page.goto(cate["url"], wait_until="networkidle", timeout=45000)
                time.sleep(3)

                # Tự động cuộn trang để kích hoạt tải dữ liệu
                for _ in range(4):
                    page.mouse.wheel(0, 1500)
                    time.sleep(1)

                # Gọi trực tiếp API nội bộ thông qua ngữ cảnh trình duyệt đã vượt tường lửa
                api_script = f"""
                async () => {{
                    try {{
                        const res = await fetch("https://api.avakids.com/gw/bus-ava-tmdt/api/Cate/GetproductCateV2", {{
                            method: "POST",
                            headers: {{
                                "content-type": "application/json",
                                "provinceid": "1027",
                                "siteid": "17",
                                "os": "WebAVAKids",
                                "platform": "1"
                            }},
                            body: JSON.stringify({{
                                pageIndex: 0,
                                pageSize: 1000,
                                provinceId: 1027,
                                urlCate: "{cate['url'].replace('https://www.avakids.com', '')}",
                                cateId: "{cate['cate_id']}",
                                filters: [{{ filterId: 1, filterTypeId: 6, sortName: "FEATURED_PRODUCTS", url: "" }}]
                            }})
                        }});
                        const json = await res.json();
                        return json?.data?.products || [];
                    }} catch (e) {{
                        return [];
                    }}
                }}
                """
                products = page.evaluate(api_script)
                print(f"[+] Lấy thành công {len(products)} sản phẩm cho {cate['name']}")

                for item in products:
                    p_code = item.get('productCode') or item.get('productPEId') or ""
                    p_name = item.get('name') or ""
                    if not p_code or not p_name or p_code in seen:
                        continue
                    seen.add(p_code)

                    p_prices = item.get('productPrices', [{}])[0] if item.get('productPrices') else {}
                    sale_price = clean_price(p_prices.get('price', 0))
                    orig_price = clean_price(p_prices.get('originalPrice') or p_prices.get('hisPrice') or sale_price)
                    if orig_price == 0:
                        orig_price = sale_price

                    promos = []
                    if item.get('gift', {}).get('name'):
                        promos.append(f"Tặng: {item['gift']['name']}")
                    if item.get('lstTextPromotion'):
                        for tp in item['lstTextPromotion']:
                            for b in tp.get('lstBlockTextPromotion', []):
                                for html_t in b.get('subTitle', []):
                                    txt = clean_html(html_t)
                                    if txt:
                                        promos.append(txt)
                    promo_str = " | ".join(promos)

                    short_desc = clean_html(item.get('shortDescription') or "")
                    detail_desc = clean_html(item.get('description') or short_desc)
                    brand = item.get('brandName') or ""
                    img_url = item.get('avatar') or ""
                    if img_url and not img_url.startswith("http"):
                        img_url = f"https://cdn.avakids.com{img_url}"
                    prod_url = f"https://www.avakids.com{item.get('url', '')}" if item.get('url') else ""
                    age = extract_target_age(p_name)

                    all_rows.append([
                        p_code, "", p_name, brand, cate["name"], age,
                        orig_price, sale_price, promo_str, short_desc, detail_desc, "",
                        img_url, prod_url, now_str
                    ])
            except Exception as e:
                print(f"Lỗi khi xử lý ngành {cate['name']}: {e}")

        browser.close()

    if all_rows:
        print(f"[*] Đang ghi {len(all_rows)} sản phẩm vào Google Sheets...")
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
        print(f"🎉 Cập nhật thành công {len(all_rows)} sản phẩm lên Google Sheet!")
    else:
        print("[!] Không lấy được dữ liệu sản phẩm.")

if __name__ == "__main__":
    main()
