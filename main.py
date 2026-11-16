
import utils.transport
import utils.session
import asyncio
import re
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

# Start-Process "C:\Program Files\Google\Chrome\Application\chrome.exe" -ArgumentList '--remote-debugging-port=9222 --user-data-dir=C:\TatkalChromeProfile'

CDP_URL = "http://127.0.0.1:9222"
IRCTC_DOMAIN = "https://www.irctc.co.in"
PAYMENT_TYPE_RADIO = (
    'p-radiobutton[formcontrolname="paymentType"][id="2"] [role="radio"]'
)
CONTINUE_GUARD_KEY = "tatkal_assistant_continue_to_review_attempted"
REVIEW_CONTINUE_GUARD_KEY = "tatkal_assistant_review_continue_attempted"
MULTIPLE_PAYMENT_GUARD_KEY = "tatkal_assistant_multiple_payment_selected"

PASSENGERS = (
    {
        "name": "Lalit Govindram",
        "suggestion_name": "Lalit govindram sutar",
        "age": 32,
        "gender": "Male",
        "nationality": "India",
        "berth_preference": "No Preference",
    },
    {
        "name": "Rekha Sutar",
        "suggestion_name": "Rekha Sutar",
        "age": 28,
        "gender": "Female",
        "nationality": "India",
        "berth_preference": "No Preference",
    },
)


def identify_page(url):
    if "/nget/train-search" in url:
        return "IRCTC TRAIN SEARCH PAGE"

    if "/nget/payment/bkgPaymentOptions" in url:
        return "PAYMENT OPTIONS PAGE"

    if "/nget/booking/psgninput" in url:
        return "PASSENGER DETAILS PAGE"

    if "/nget/booking/reviewBooking" in url:
        return "REVIEW BOOKING PAGE"

    if "/nget/booking" in url:
        return "BOOKING PAGE"

    return "OTHER IRCTC PAGE"


async def inspect_passenger_page(page) -> bool:
    print("\n========== PASSENGER PAGE INSPECTION ==========")

    if "/nget/booking/psgninput" not in page.url:
        print("Passenger Details page not detected.")
        return False

    print("Passenger Details page detected.")

    passenger_panel = page.locator(".ui-panel-titlebar").filter(
        has_text="Passenger Details"
    )
    panel_toggle = passenger_panel.locator(
        '[role="tab"][aria-expanded]'
    )

    try:
        await panel_toggle.wait_for(state="visible", timeout=5000)
    except PlaywrightTimeoutError:
        print("Could not find the Passenger Details panel toggle.")
        return False

    panel_expanded = await panel_toggle.get_attribute("aria-expanded")
    if panel_expanded == "false":
        await panel_toggle.click()
        try:
            await page.wait_for_function(
                """() => {
                    const header = [...document.querySelectorAll(".ui-panel-titlebar")]
                        .find((element) => element.textContent.includes("Passenger Details"));
                    return header
                        ?.querySelector('[role="tab"][aria-expanded]')
                        ?.getAttribute("aria-expanded") === "true";
                }""",
                timeout=5000
            )
        except PlaywrightTimeoutError:
            print("Passenger Details panel did not expand.")
            return False
    elif panel_expanded != "true":
        print("Passenger Details panel state is unknown.")
        return False

    name_fields = page.get_by_placeholder(
        "Full Name as per Govt. ID",
        exact=True
    )

    for index, passenger in enumerate(PASSENGERS):
        if await name_fields.count() <= index:
            add_passenger = page.get_by_text(
                "Add Passenger/ Add Infant With Berth",
                exact=False
            )
            if await add_passenger.count() == 0:
                print("Could not find the Add Passenger control.")
                return False

            await add_passenger.first.click()

        try:
            name_field = name_fields.nth(index)
            await name_field.wait_for(
                state="visible",
                timeout=5000
            )
        except PlaywrightTimeoutError:
            print(f"Passenger name field {index + 1} is not available.")
            return False

        current_value = (await name_field.input_value()).strip()
        if current_value.casefold() == passenger["name"].casefold():
            print(f"{passenger['name']} is already selected.")
            continue
        if current_value:
            print(f"Passenger field {index + 1} is not empty; leaving it unchanged.")
            return False

        await name_field.fill(passenger["name"])

        list_id = await name_field.get_attribute("aria-controls")
        if not list_id:
            print(f"Autocomplete list was not identified for {passenger['name']}.")
            return False

        suggestion_list = page.locator(f'[id="{list_id}"]')
        suggestions = suggestion_list.get_by_role("option")

        try:
            await suggestions.first.wait_for(state="visible", timeout=5000)
        except PlaywrightTimeoutError:
            print(f"No saved-passenger suggestions appeared for {passenger['name']}.")
            print("The typed name was left in the field for manual review.")
            return False

        matching_suggestion = None
        age_pattern = re.compile(
            rf"\b{passenger['age']}\s*(?:yrs?|years?)\b",
            re.IGNORECASE
        )

        for suggestion_index in range(await suggestions.count()):
            suggestion = suggestions.nth(suggestion_index)
            if not await suggestion.is_visible():
                continue

            suggestion_text = " ".join((await suggestion.inner_text()).split())
            if (
                passenger["suggestion_name"].casefold() in suggestion_text.casefold()
                and age_pattern.search(suggestion_text)
                and passenger["gender"].casefold() in suggestion_text.casefold()
            ):
                matching_suggestion = suggestion
                break

        if matching_suggestion is None:
            await name_field.fill("")
            print(
                f"No saved suggestion matched the name, age, and gender "
                f"for {passenger['name']}. The field was cleared."
            )
            return False

        await matching_suggestion.click()
        print(f"Selected saved passenger: {passenger['name']}.")

    print("===============================================")
    print("Both saved passengers are selected.")
    return True


async def select_payment_type_option(page) -> bool:
    radio = page.locator(PAYMENT_TYPE_RADIO)

    if await radio.count() == 0:
        return False

    try:
        await radio.wait_for(state="visible", timeout=5000)
    except PlaywrightTimeoutError:
        print("Payment type option 2 is not visible; leaving it unchanged.")
        return False

    checked = await radio.get_attribute("aria-checked")
    if checked == "true":
        print("Payment type option 2 is already selected.")
        return True
    if checked != "false":
        print("Could not determine payment type option 2 state; leaving it unchanged.")
        return False

    await radio.click()
    try:
        await page.wait_for_function(
            """(selector) => {
                const radio = document.querySelector(selector);
                return radio?.getAttribute("aria-checked") === "true";
            }""",
            arg=PAYMENT_TYPE_RADIO,
            timeout=5000
        )
    except PlaywrightTimeoutError:
        print("Payment type option 2 selection was not confirmed.")
        return False

    print("Selected payment type option 2. No booking or payment was submitted.")
    return True


async def click_continue_to_review(page):
    if identify_page(page.url) == "REVIEW BOOKING PAGE":
        print("Review page already reached; not clicking Continue again.")
        return

    continue_buttons = page.get_by_role("button", name="Continue", exact=True)
    try:
        await continue_buttons.first.wait_for(state="visible", timeout=5000)
    except PlaywrightTimeoutError:
        print("Continue button not found; leaving the next step manual.")
        return

    matching_buttons = [
        continue_buttons.nth(index)
        for index in range(await continue_buttons.count())
        if await continue_buttons.nth(index).is_visible()
    ]

    if len(matching_buttons) != 1:
        print(
            f"Found {len(matching_buttons)} visible Continue buttons; "
            "leaving the next step manual."
        )
        return

    if not await matching_buttons[0].is_enabled():
        print("Continue is disabled; the booking form is blocking the next step.")
        return

    can_click = await page.evaluate(
        """(key) => {
            if (sessionStorage.getItem(key) === "true") {
                return false;
            }
            sessionStorage.setItem(key, "true");
            return true;
        }""",
        CONTINUE_GUARD_KEY
    )
    if not can_click:
        print("Continue was already attempted in this tab; leaving it unchanged.")
        return

    print("Clicking Continue once to open the review page.")
    try:
        await matching_buttons[0].click(timeout=10000)
    except PlaywrightTimeoutError:
        await reset_continue_guard(page)
        print("Continue could not be activated; check whether the button is enabled.")
        return

    try:
        await page.wait_for_url(
            "**/nget/booking/reviewBooking",
            timeout=10000
        )
    except PlaywrightTimeoutError:
        await reset_continue_guard(page)
        print("Continue was clicked, but the review page was not confirmed.")
        print("The one-time guard was cleared; check the page before retrying.")
        return

    print("Review page reached.")


async def click_continue_from_review(page):
    if identify_page(page.url) != "REVIEW BOOKING PAGE":
        return

    continue_buttons = page.get_by_role("button", name="Continue", exact=True)
    try:
        await continue_buttons.first.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError:
        print("Review-page Continue button not found; leaving this step manual.")
        return

    visible_buttons = [
        continue_buttons.nth(index)
        for index in range(await continue_buttons.count())
        if await continue_buttons.nth(index).is_visible()
    ]
    if len(visible_buttons) != 1:
        print(
            f"Found {len(visible_buttons)} visible Continue buttons on the review page; "
            "leaving this step manual."
        )
        return

    button = visible_buttons[0]
    if not await button.is_enabled():
        print("Review-page Continue is disabled; leaving this step manual.")
        return

    can_click = await page.evaluate(
        """(key) => {
            if (sessionStorage.getItem(key) === "true") {
                return false;
            }
            sessionStorage.setItem(key, "true");
            return true;
        }""",
        REVIEW_CONTINUE_GUARD_KEY
    )
    if not can_click:
        # The old guard was written before the click. If this tab is still on
        # the review page, that attempt did not advance the booking flow, so
        # allow one fresh attempt instead of leaving the user stuck forever.
        await page.evaluate(
            "(key) => sessionStorage.removeItem(key)",
            REVIEW_CONTINUE_GUARD_KEY
        )
        print("Cleared a stale review-page Continue guard; retrying the click.")
        can_click = await page.evaluate(
            """(key) => {
                if (sessionStorage.getItem(key) === "true") {
                    return false;
                }
                sessionStorage.setItem(key, "true");
                return true;
            }""",
            REVIEW_CONTINUE_GUARD_KEY
        )
        if not can_click:
            print("Could not reset the review-page Continue guard.")
            return

    print("Clicking review-page Continue once.")
    try:
        await button.click(timeout=10000)
    except PlaywrightTimeoutError:
        await page.evaluate(
            "(key) => sessionStorage.removeItem(key)",
            REVIEW_CONTINUE_GUARD_KEY
        )
        print("Review-page Continue could not be activated; leaving this step manual.")
        return

    try:
        await page.wait_for_url(
            lambda url: identify_page(url) != "REVIEW BOOKING PAGE",
            timeout=10000
        )
    except PlaywrightTimeoutError:
        await page.evaluate(
            "(key) => sessionStorage.removeItem(key)",
            REVIEW_CONTINUE_GUARD_KEY
        )
        print("Continue was clicked, but the review page did not advance.")
        print("The one-time guard was cleared; check the page before retrying.")
        return

    print("Review page advanced. Payment submission and final booking remain manual.")


async def select_multiple_payment_service(page):
    if identify_page(page.url) != "PAYMENT OPTIONS PAGE":
        return

    tiles = page.locator("div.bank-type")
    try:
        await tiles.filter(
            has_text="Multiple Payment Service"
        ).first.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError:
        print("Multiple Payment Service option not found; leaving this step manual.")
        return

    matches = []
    for index in range(await tiles.count()):
        tile = tiles.nth(index)
        if not await tile.is_visible():
            continue
        text = " ".join((await tile.inner_text()).split())
        if text == "Multiple Payment Service":
            matches.append(tile)

    if len(matches) != 1:
        print(
            f"Found {len(matches)} visible Multiple Payment Service options; "
            "leaving this step manual."
        )
        return

    tile = matches[0]
    classes = (await tile.get_attribute("class") or "").split()
    if "bank-type-active" in classes:
        print("Multiple Payment Service is active; clicking it once as requested.")

    can_click = await page.evaluate(
        """(key) => {
            if (sessionStorage.getItem(key) === "true") {
                return false;
            }
            sessionStorage.setItem(key, "true");
            return true;
        }""",
        MULTIPLE_PAYMENT_GUARD_KEY
    )
    if not can_click:
        print("Multiple Payment Service was already attempted in this tab.")
        return

    print("Selecting Multiple Payment Service once.")
    try:
        await tile.click(timeout=10000)
        await page.wait_for_function(
            """() => [...document.querySelectorAll("div.bank-type")].some(
                (element) =>
                    element.innerText.trim() === "Multiple Payment Service" &&
                    element.classList.contains("bank-type-active")
            )""",
            timeout=5000
        )
    except PlaywrightTimeoutError:
        await page.evaluate(
            "(key) => sessionStorage.removeItem(key)",
            MULTIPLE_PAYMENT_GUARD_KEY
        )
        print("Multiple Payment Service selection was not confirmed.")
        return

    print("Multiple Payment Service selected. No payment was submitted.")


async def reset_continue_guard(page):
    await page.evaluate(
        "(key) => sessionStorage.removeItem(key)",
        CONTINUE_GUARD_KEY
    )


async def reset_review_continue_guard(page):
    await page.evaluate(
        "(key) => sessionStorage.removeItem(key)",
        REVIEW_CONTINUE_GUARD_KEY
    )


async def reset_multiple_payment_guard(page):
    await page.evaluate(
        "(key) => sessionStorage.removeItem(key)",
        MULTIPLE_PAYMENT_GUARD_KEY
    )


async def watch_for_payment_type_option(page, passenger_selection_complete):
    print("Watching for payment type option 2 on this IRCTC tab.")

    while not page.is_closed():
        if (
            passenger_selection_complete.is_set()
            and page.url.startswith(IRCTC_DOMAIN)
        ):
            is_active_tab = await page.evaluate(
                "document.visibilityState === 'visible'"
            )
            if is_active_tab:
                radio = page.locator(PAYMENT_TYPE_RADIO)
                if await radio.count() > 0 and await radio.is_visible():
                    print("Payment type radio detected on the active IRCTC tab.")
                    if await select_payment_type_option(page):
                        await click_continue_to_review(page)
                    return

        await asyncio.sleep(1)


def monitor_navigation(page):
    inspected_passenger_urls = set()
    payment_options_urls = set()
    passenger_selection_complete = asyncio.Event()

    def schedule_passenger_inspection(url):
        if url in inspected_passenger_urls:
            return

        inspected_passenger_urls.add(url)

        async def inspect_and_mark_complete():
            if await inspect_passenger_page(page):
                passenger_selection_complete.set()
            else:
                print(
                    "Payment selection and Continue are paused until both "
                    "passengers are selected."
                )

        asyncio.create_task(inspect_and_mark_complete())

    def schedule_payment_service_selection(url):
        if url in payment_options_urls:
            return

        payment_options_urls.add(url)
        asyncio.create_task(select_multiple_payment_service(page))

    def on_navigation(frame):
        if frame == page.main_frame:
            print("\n--------------------------------")
            print("IRCTC PAGE NAVIGATION DETECTED")
            print("Page:", identify_page(page.url))
            print("URL:", page.url)
            print("--------------------------------")

            if "/nget/train-search" in page.url:
                passenger_selection_complete.clear()
                asyncio.create_task(reset_continue_guard(page))
                asyncio.create_task(reset_review_continue_guard(page))
                asyncio.create_task(reset_multiple_payment_guard(page))
            elif "/nget/booking/psgninput" in page.url:
                print("Passenger Details page detected.")
                schedule_passenger_inspection(page.url)
            elif identify_page(page.url) == "REVIEW BOOKING PAGE":
                asyncio.create_task(click_continue_from_review(page))
            elif identify_page(page.url) == "PAYMENT OPTIONS PAGE":
                schedule_payment_service_selection(page.url)

    page.on("framenavigated", on_navigation)
    asyncio.create_task(
        watch_for_payment_type_option(page, passenger_selection_complete)
    )

    if "/nget/booking/psgninput" in page.url:
        schedule_passenger_inspection(page.url)
    elif identify_page(page.url) == "REVIEW BOOKING PAGE":
        asyncio.create_task(click_continue_from_review(page))
    elif identify_page(page.url) == "PAYMENT OPTIONS PAGE":
        schedule_payment_service_selection(page.url)


async def main():
    async with async_playwright() as p:

        print("\nConnecting to existing Chrome...")

        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)

        except Exception as error:
            print("\nChrome connection failed.")
            print("Make sure Chrome is running with remote debugging on port 9222.")
            print("Error:", error)
            return

        if not browser.contexts:
            print("No Chrome browser context found.")
            return

        context = browser.contexts[0]

        irctc_pages = [
            page for page in context.pages
            if page.url.startswith(IRCTC_DOMAIN)
        ]

        if not irctc_pages:
            print("\nNo IRCTC tab found.")
            print("Open IRCTC in the debugging-enabled Chrome window.")
            return

        page = None
        for candidate in irctc_pages:
            if await candidate.evaluate("document.visibilityState") == "visible":
                page = candidate
                break

        if page is None:
            page = irctc_pages[-1]

        await page.bring_to_front()

        print("\n================================")
        print("CONNECTED SUCCESSFULLY!")
        print("================================")
        print("Current page:", identify_page(page.url))
        print("Current URL:", page.url)
        print("Monitoring the active IRCTC tab.")

        monitor_navigation(page)

        if (
            "/nget/train-search" in page.url
            or "/nget/booking/psgninput" in page.url
        ):
            await reset_continue_guard(page)
        if "/nget/train-search" in page.url:
            await reset_review_continue_guard(page)
            await reset_multiple_payment_guard(page)

        def on_new_page(new_page):
            print("\nNew browser tab detected.")
            monitor_navigation(new_page)

        context.on("page", on_new_page)

        print("\n================================")
        print("IRCTC MONITOR IS RUNNING")
        print("================================")
        print("Chrome session remains open.")
        print("Saved passenger selection is enabled on the Passenger Details page.")
        print("Each automated step is attempted once per tab.")
        print("Review-page Continue and Multiple Payment Service are each handled once.")
        print("Payment submission and booking confirmation remain manual.")
        print("Booking submission and payment authorization remain manual.")

        await asyncio.to_thread(
            input,
            "\nPress ENTER to stop monitoring..."
        )

        print("\nMonitoring stopped.")
        print("Your Chrome browser remains open.")


if __name__ == "__main__":
    asyncio.run(main())
