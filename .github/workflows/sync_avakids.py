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
    {"url": "https://www.avakids.com/sua-bot-cho-be", "name": "Sữa bột"},
    {"url": "https://www.avakids.com/sua-pha-san-cho-be", "name": "Sữa pha sẵn"}
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

    print("[*] Khởi chạy Playwright Chromium để cào trực tiếp giao diện...")
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
            viewport={"width": 1440, "height": 900}
        )
        page = context.new_page()

        for cate in CATE_LIST:
            print(f"[*] Đang tải trang: {cate['name']} ({cate['url']})...")
            try:
                page.goto(cate["url"], wait_until="networkidle", timeout=60000)
                time.sleep(3)

                # Bấm xem thêm / cuộn trang để nạp danh sách sản phẩm
                print(f"[*] Đang cuộn trang tải toàn bộ sản phẩm {cate['name']}...")
                for scroll_idx in range(12):
                    page.mouse.wheel(0, 3000)
                    time.sleep(1.5)
                    # Thử click nút "Xem thêm" nếu xuất hiện
                    try:
                        view_more = page.locator(".view-more, .btn-viewmore, a:has-text('Xem thêm')").first
                        if view_more.is_visible():
                            view_more.click(timeout=1000)
                            time.sleep(1.5)
                    except Exception:
                        pass

                # Trích xuất toàn bộ sản phẩm trực tiếp từ DOM
                products_data = page.evaluate("""
                () => {
                    const items = [];
                    // Danh sách selector các thẻ sản phẩm phổ biến trên AVAKids
                    const elements = document.querySelectorAll('li.item, .product-item, .item-product, ul.listproduct > li');
                    elements.forEach(el => {
                        try {
                            const nameEl = el.querySelector('h3, .item-name, .name, [title]');
                            const name = nameEl ? (nameEl.innerText || nameEl.getAttribute('title') || '').trim() : '';
                            if (!name) return;

                            const linkEl = el.querySelector('a');
                            const href = linkEl ? linkEl.getAttribute('href') : '';

                            const priceEl = el.querySelector('.price, strong.price, .box-price strong');
                            const priceText = priceEl ? priceEl.innerText : '0';

                            const oldPriceEl = el.querySelector('.old-price, .box-price cite, strike');
                            const oldPriceText = oldPriceEl ? oldPriceEl.innerText : '0';

                            const imgEl = el.querySelector('img');
                            let imgUrl = '';
                            if (imgEl) {
                                imgUrl = imgEl.getAttribute('data-src') || imgEl.getAttribute('src') || '';
                            }

                            const promoEl = el.querySelector('.item-gift, .item-promos, .text-promotion');
                            const promoText = promoEl ? promoEl.innerText.trim() : '';

                            const code = el.getAttribute('data-id') || el.getAttribute('data-product-code') || href;

                            items.push({
                                code: code,
                                name: name,
                                href: href,
                                priceText: priceText,
                                oldPriceText: oldPriceText,
                                imgUrl: imgUrl,
                                promoText: promoText
                            });
                        } catch (err) {}
                    });
                    return items;
                }
                """)

                print(f"[+] Tìm thấy {len(products_data)} sản phẩm trên giao diện cho ngành {cate['name']}")

                for item in products_data:
                    p_name = item.get('name') or ""
                    p_href = item.get('href') or ""
                    p_code = item.get('code') or p_name
                    
                    if not p_name or p_name in seen:
                        continue
                    seen.add(p_name)

                    sale_price = clean_price(item.get('priceText'))
                    orig_price = clean_price(item.get('oldPriceText'))
                    if orig_price == 0:
                        orig_price = sale_price

                    img_url = item.get('imgUrl') or ""
                    if img_url and not img_url.startswith("http"):
                        img_url = f"https:{img_url}" if img_url.startswith("//") else f"https://cdn.avakids.com{img_url}"

                    prod_url = p_href if p_href.startswith("http") else f"https://www.avakids.com{p_href}"
                    age = extract_target_age(p_name)

                    # Phân tích thương hiệu từ tên
                    brand_guess = ""
                    common_brands = ['Pediasure', 'Nan', 'Similac', 'Enfagrow', 'Aptamil', 'Friso', 'Meiji', 'Morinaga', 'Glico', 'ColosBaby', 'Dielac', 'Optimum', 'Vinamilk', 'TH true MILK', 'Nestlé', 'Nutifood', 'Abbott']
                    for b in common_brands:
                        if b.lower() in p_name.lower():
                            brand_guess = b
                            break

                    all_rows.append([
                        p_code, "", p_name, brand_guess, cate["name"], age,
                        orig_price, sale_price, item.get('promoText', ''), "", "", "",
                        img_url, prod_url, now_str
                    ])

            except Exception as e:
                print(f"[-] Lỗi khi xử lý ngành {cate['name']}: {e}")

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
        print("[!] Vẫn chưa lấy được dữ liệu từ giao diện.")

if __name__ == "__main__":
    main()
