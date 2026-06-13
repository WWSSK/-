import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait


PRODUCT_IDS = [
    "OLJCESPC7Z",
    "66VCHSJNUP",
    "1YMWWN1N4O",
    "L9ECAV7KIM",
    "2ZYFJ3GM2N",
    "0PUK6V6EV0",
    "LS4PSXUNUM",
    "9SIQT8TOJO",
    "6E92ZMYYFZ",
]


def build_driver(headless: bool) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1440,1000")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    return webdriver.Chrome(options=options)


def wait_for_page(driver: webdriver.Chrome, timeout: int = 15) -> WebDriverWait:
    return WebDriverWait(driver, timeout)


def click_first_available(driver: webdriver.Chrome, selectors: list[tuple[str, str]], timeout: int = 10) -> None:
    wait = wait_for_page(driver, timeout)
    last_error = None
    for by, selector in selectors:
        try:
            element = wait.until(EC.element_to_be_clickable((by, selector)))
            element.click()
            return
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Could not click any selector: {selectors}") from last_error


def type_if_present(driver: webdriver.Chrome, name: str, value: str) -> None:
    fields = driver.find_elements(By.NAME, name)
    if fields:
        fields[0].clear()
        fields[0].send_keys(value)


def choose_if_present(driver: webdriver.Chrome, name: str, value: str) -> None:
    fields = driver.find_elements(By.NAME, name)
    if fields:
        Select(fields[0]).select_by_value(value)


def add_product_to_cart(driver: webdriver.Chrome, base_url: str, product_id: str) -> None:
    driver.get(f"{base_url.rstrip('/')}/product/{product_id}")
    wait_for_page(driver).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

    quantity = driver.find_elements(By.NAME, "quantity")
    if quantity:
        try:
            Select(quantity[0]).select_by_value("1")
        except Exception:
            quantity[0].clear()
            quantity[0].send_keys("1")

    click_first_available(
        driver,
        [
            (By.CSS_SELECTOR, "button[type='submit']"),
            (By.XPATH, "//button[contains(., 'Add To Cart')]"),
            (By.XPATH, "//input[@type='submit']"),
        ],
    )


def checkout(driver: webdriver.Chrome, base_url: str) -> None:
    driver.get(f"{base_url.rstrip('/')}/cart")
    wait_for_page(driver).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

    click_first_available(
        driver,
        [
            (By.XPATH, "//button[contains(., 'Place Order')]"),
            (By.XPATH, "//button[contains(., 'Checkout')]"),
            (By.CSS_SELECTOR, "button[type='submit']"),
        ],
        timeout=8,
    )

    wait_for_page(driver).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

    form_values = {
        "email": "student@example.com",
        "street_address": "1 Software Testing Road",
        "zip_code": "300000",
        "city": "Tianjin",
        "state": "TJ",
        "country": "China",
        "credit_card_number": "4111111111111111",
        "credit_card_cvv": "123",
    }
    for name, value in form_values.items():
        type_if_present(driver, name, value)

    choose_if_present(driver, "credit_card_expiration_month", "1")
    choose_if_present(driver, "credit_card_expiration_year", "2030")

    click_first_available(
        driver,
        [
            (By.XPATH, "//button[contains(., 'Place Order')]"),
            (By.XPATH, "//button[contains(., 'Pay')]"),
            (By.CSS_SELECTOR, "button[type='submit']"),
        ],
        timeout=8,
    )


def run_once(driver: webdriver.Chrome, base_url: str, product_id: str) -> dict:
    started = time.perf_counter()
    timestamp = datetime.now().isoformat(timespec="seconds")
    status = "pass"
    error = ""
    try:
        driver.get(base_url)
        wait_for_page(driver).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        add_product_to_cart(driver, base_url, product_id)
        checkout(driver, base_url)
        wait_for_page(driver, 20).until(
            lambda d: "order" in d.page_source.lower()
            or "confirmation" in d.page_source.lower()
            or "thank" in d.page_source.lower()
        )
    except TimeoutException as exc:
        status = "fail"
        error = f"timeout: {exc}"
    except Exception as exc:
        status = "fail"
        error = str(exc)

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "timestamp": timestamp,
        "base_url": base_url,
        "product_id": product_id,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "error": error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Selenium checkout test for Online Boutique.")
    parser.add_argument("--base-url", default=os.getenv("BASE_URL", " http://127.0.0.1:50539"))
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--output", default="selenium-results.json")
    args = parser.parse_args()

    driver = build_driver(args.headless)
    results = []
    try:
        for index in range(args.rounds):
            product_id = PRODUCT_IDS[index % len(PRODUCT_IDS)]
            # 运行下单逻辑
            result = run_once(driver, args.base_url.rstrip("/").strip(), product_id)
            results.append(result)
            print(json.dumps(result, ensure_ascii=False))
        
        # 【重要修改 2】：在成功运行后加入暂停，让你有时间看一眼浏览器
        print("\n" + "="*30)
        print("🎉 脚本执行完毕！请手动检查浏览器页面。")
        input("👉 请在确认后，回到这里按【回车键(Enter)】关闭浏览器并退出...")

    except Exception as e:
        # 【重要修改 3】：如果运行中报错，也会停下来让你看错误原因
        print(f"\n❌ 脚本运行出错: {e}")
        input("👉 发生错误，按【回车键(Enter)】查看浏览器状态并关闭...")
        
    finally:
        # 【重要修改 4】：Python 注释必须用 #
        # 如果你想让浏览器彻底不关，可以把下面这一行删掉或注释掉
        driver.quit()

    output_path = Path(args.output)
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if all(item["status"] == "pass" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
