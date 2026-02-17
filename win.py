import json
import time
from urllib.parse import urljoin
from pathlib import Path
import platform

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService


PLAYLIST_URL = "YOUR LINK TO THE PLAYLIST"
OUTPUT_JSON = "playlist_min.json"

TRACK_LINK_SELECTOR = 'a[data-testid="internal-track-link"][href^="/track/"]'


def extract_track_id(track_href: str) -> str:
    path = track_href.split("?", 1)[0]
    return path.rsplit("/", 1)[-1]

def find_scroll_container(driver, any_track_link):
    return driver.execute_script(
        """
        function isScrollable(el) {
          if (!el) return false;
          const s = window.getComputedStyle(el);
          const oy = s.overflowY;
          const can = (oy === 'auto' || oy === 'scroll');
          return can && el.scrollHeight > el.clientHeight + 5;
        }
        let el = arguments[0];
        while (el && el !== document.body) {
          if (isScrollable(el)) return el;
          el = el.parentElement;
        }
        return document.scrollingElement || document.documentElement;
        """,
        any_track_link,
    )


def is_playlist_row_track_link(a) -> bool:
    """
    Heuristic filter to exclude 'recommended' tracks:
    playlist rows have a numeric index in the first gridcell (aria-colindex="1").
    """
    try:
        row = a.find_element(By.XPATH, "./ancestor::*[@role='row'][1]")
    except Exception:
        return False

    try:
        idx_cell = row.find_element(By.CSS_SELECTOR, '[role="gridcell"][aria-colindex="1"]')
    except Exception:
        return False

    text = (idx_cell.text or "").strip()
    return text.isdigit()


def parse_track_from_link(a) -> dict | None:
    href = a.get_attribute("href") or ""
    if not href:
        return None

    track_id = extract_track_id(href)
    name = a.text.strip()

    try:
        row = a.find_element(By.XPATH, "./ancestor::*[@role='row'][1]")
    except Exception:
        return None

    artist_els = row.find_elements(By.CSS_SELECTOR, 'a[href^="/artist/"]')
    artists = []
    for el in artist_els:
        t = (el.text or "").strip()
        if t and t not in artists:
            artists.append(t)

    full_link = href if href.startswith("http") else urljoin(PLAYLIST_URL, href)

    return {
        "id": track_id,
        "name": name,
        "artists": artists,
        "link": full_link,
        "embed_url": urljoin(PLAYLIST_URL, f"/embed/track/{track_id}"),
    }


def scroll_collect_all_tracks(driver, scroll_container) -> list[dict]:
    tracks_by_id: dict[str, dict] = {}

    stable_rounds = 0
    max_stable_rounds = 8

    while stable_rounds < max_stable_rounds:
        before = len(tracks_by_id)

        # Collect currently rendered rows
        links = driver.find_elements(By.CSS_SELECTOR, TRACK_LINK_SELECTOR)
        for a in links:
            if not is_playlist_row_track_link(a):
                continue
            t = parse_track_from_link(a)
            if not t:
                continue
            tracks_by_id[t["id"]] = t

        after = len(tracks_by_id)

        # Scroll one "page" down inside the container
        driver.execute_script(
            """
            const el = arguments[0];
            el.scrollTop = el.scrollTop + Math.floor(el.clientHeight * 0.85);
            """,
            scroll_container,
        )
        time.sleep(0.6)

        # Determine if we are at the bottom of the container
        at_bottom = driver.execute_script(
            """
            const el = arguments[0];
            return (el.scrollHeight - el.scrollTop - el.clientHeight) < 5;
            """,
            scroll_container,
        )

        if after == before:
            # no new tracks this round
            stable_rounds += 1
        else:
            stable_rounds = 0

        # If we're at bottom and nothing new appears, we're done
        if at_bottom and stable_rounds >= 3:
            break

    return list(tracks_by_id.values())


def collect_tracks(driver) -> list[dict]:
    wait = WebDriverWait(driver, 20)

    driver.get(PLAYLIST_URL)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, TRACK_LINK_SELECTOR)))

    first_link = driver.find_element(By.CSS_SELECTOR, TRACK_LINK_SELECTOR)
    scroll_container = find_scroll_container(driver, first_link)

    tracks = scroll_collect_all_tracks(driver, scroll_container)
    return tracks


def main():
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless=new")  # uncomment if you want headless
    options.add_argument("--window-size=1400,900")

    # Windows-friendly: avoid random "DevToolsActivePort" / profile locking issues
    if platform.system().lower().startswith("win"):
        profile_dir = Path.home() / "AppData" / "Local" / "spotify_scraper_chrome_profile"
        options.add_argument(f"--user-data-dir={profile_dir}")

    # Selenium 4.6+ uses Selenium Manager to locate/download a matching ChromeDriver automatically.
    # Passing an explicit Service keeps it predictable across OSes (including Windows).
    service = ChromeService()
    driver = webdriver.Chrome(service=service, options=options)
    try:
        tracks = collect_tracks(driver)
    finally:
        driver.quit()

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(tracks, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(tracks)} tracks to {OUTPUT_JSON}")


if __name__ == "__main__":
    main()