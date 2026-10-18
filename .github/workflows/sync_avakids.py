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
    all_rows = []
    seen = set()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("[*] Khởi chạy Playwright Chromium để vượt qua Cloudflare WAF...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768}
        )
        page = context.new_page()

        # 1. Truy cập trang chủ AVAKids để lấy TLS Certificate & Cookie phiên làm việc hợp lệ
        print("[*] Đang khởi tạo phiên làm việc với máy chủ AVAKids...")
        page.goto("https://www.avakids.com", wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)

        # 2. Thu thập dữ liệu API thông qua context trình duyệt
        for cate in CATE_LIST:
            print(f"[*] Đang lấy dữ liệu ngành: {cate['category_name']}...")
            try:
                # Điều hướng nhẹ sang danh mục để kích hoạt referer
                page.goto(f"https://www.avakids.com{cate['url_path']}", wait_until="domcontentloaded", timeout=60000)
                time.sleep(2)

                # Sử dụng fetch trực tiếp trong trang (giữ nguyên cấu trúc payload từ SOSANHGIA.PY)
                fetch_script = f"""
                async () => {{
                    try {{
                        const res = await fetch("https://api.avakids.com/gw/bus-ava-tmdt/api/Cate/GetproductCateV2", {{
                            method: "POST",
                            headers: {{
                                "content-type": "application/json",
                                "provinceid": "1027",
                                "siteid": "17",
                                "os": "WebAVAKids",
                                "platform": "1",
                                "accept": "application/json, text/plain, */*"
                            }},
                            body: JSON.stringify({{
                                pageIndex: 0,
                                pageSize: 1000,
                                provinceId: 1027,
                                urlCate: "{cate['url_path']}",
                                cateId: "{cate['cate_id']}",
                                filters: [{{ filterId: 1, filterTypeId: 6, sortName: "FEATURED_PRODUCTS", url: "" }}]
                            }})
                        }});
                        const data = await res.json();
                        return data?.data?.products || [];
                    }} catch (e) {{
                        return [];
                    }}
                }}
                """
                products = page.evaluate(fetch_script)
                print(f"[+] Lấy thành công {len(products)} sản phẩm cho {cate['category_name']}")

                for p_item in products:
                    p_code = p_item.get('productCode') or p_item.get('productPEId') or ""
                    p_name = p_item.get('name') or ""
                    if not p_code or not p_name or p_code in seen:
                        continue
                    seen.add(p_code)

                    p_prices = p_item.get('productPrices', [{}])[0] if p_item.get('productPrices') else {}
                    sale_price = clean_price(p_prices.get('price', 0))
                    orig_price = clean_price(p_prices.get('originalPrice') or p_prices.get('hisPrice') or sale_price)
                    if orig_price == 0:
                        orig_price = sale_price

                    promos = []
                    if p_item.get('gift', {}).get('name'):
                        promos.append(f"Tặng: {p_item['gift']['name']}")
                    if p_item.get('lstTextPromotion'):
                        for tp in p_item['lstTextPromotion']:
                            for b in tp.get('lstBlockTextPromotion', []):
                                for html_t in b.get('subTitle', []):
                                    txt = clean_html(html_t)
                                    if txt:
                                        promos.append(txt)
                    promo_str = " | ".join(promos)

                    short_desc = clean_html(p_item.get('shortDescription') or "")
                    detail_desc = clean_html(p_item.get('description') or short_desc)
                    brand = p_item.get('brandName') or ""
                    img_url = p_item.get('avatar') or ""
                    if img_url and not img_url.startswith("http"):
                        img_url = f"https://cdn.avakids.com{img_url}"
                    prod_url = f"https://www.avakids.com{p_item.get('url', '')}" if p_item.get('url') else ""
                    age = extract_target_age(p_name)

                    all_rows.append([
                        p_code, "", p_name, brand, cate["category_name"], age,
                        orig_price, sale_price, promo_str, short_desc, detail_desc, "",
                        img_url, prod_url, now_str
                    ])
            except Exception as e:
                print(f"[-] Lỗi khi xử lý {cate['category_name']}: {e}")

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
        print(f"🎉 Hoàn tất cập nhật {len(all_rows)} sản phẩm vào Google Sheets!")
    else:
        print("[!] Không tìm thấy dữ liệu để ghi.")

if __name__ == "__main__":
    main()
