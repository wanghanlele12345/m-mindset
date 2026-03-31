#!/usr/bin/env python3
import sys
import time
import argparse
import uiautomator2 as u2

DEVICE_SERIAL = "127.0.0.1:16384"

def human_delay(min_sec=1.0, max_sec=2.5):
    time.sleep(min_sec)

def safe_click(d, selector, timeout=5.0):
    if selector.exists(timeout=timeout):
        selector.click()
        return True
    return False

def open_book_in_weread(title, author):
    print(f"Connecting to Android device {DEVICE_SERIAL}...")
    try:
        d = u2.connect(DEVICE_SERIAL)
    except Exception as e:
        print(f"Failed to connect to device: {e}")
        return False

    # Force launch app
    try:
        d.app_start("com.tencent.weread")
    except Exception:
        # Sometimes app_start fails if u2 session resets, just try to reconnect
        d = u2.connect(DEVICE_SERIAL)
        d.app_start("com.tencent.weread")
    
    human_delay(2)
    
    # --- 1. Navigate to Home Screen with Search Bar ---
    # The search bar ID is our anchor
    search_bar = d(resourceId="com.tencent.weread:id/home_shelf_search_bar")
    max_loops = 10
    loops = 0
    
    while not search_bar.exists and loops < max_loops:
        print(f"Search bar not found. Escaping current view ({loops + 1}/{max_loops})")
        
        # Check if we have the reader menu open
        reader_back = d(resourceId="com.tencent.weread:id/reader_top_backbutton")
        if reader_back.exists:
            print("Found reader top back button. Tapping it.")
            reader_back.click()
        else:
            # Maybe we are in the reading view without menus open?
            # Or maybe we are in a dialog?
            # Let's tap the center of the screen to reveal reading menus just in case
            print("Tapping center of screen... ")
            d.click(0.5, 0.5)
            human_delay(1)
            
            # Check again
            if d(resourceId="com.tencent.weread:id/reader_top_backbutton").exists:
                print("Reader menus appeared. Tapping back.")
                d(resourceId="com.tencent.weread:id/reader_top_backbutton").click()
            else:
                # If menus didn't appear, we are probably not in reading mode. Use system back.
                print("Pressing system back.")
                d.press("back")
                
        human_delay(1.5)
        loops += 1

    if not search_bar.exists:
        print("Could not return to home screen after multiple attempts. Relaunching app.")
        d.app_stop("com.tencent.weread")
        human_delay(2)
        d.app_start("com.tencent.weread")
        print("Waiting up to 10 seconds for the search bar to appear (splash screen)...")
        search_bar.wait(timeout=10.0)
        
        if not search_bar.exists:
            print("Failed to find Search Bar even after fresh launch.")
            return False

    print("Found Home Search Bar.")
    search_bar.click()
    human_delay(2)
    
    # --- 2. Input Search Query ---
    # Look for the input field
    search_input = d(className="android.widget.EditText")
    if not search_input.exists(timeout=3):
        print("Wait, couldn't find EditText for search.")
        return False
        
    query = f"{title}"
    if author:
        query += f" {author}"
        
    print(f"Typing search query: '{query}'")
    search_input.clear_text()
    search_input.set_text(query)
    human_delay(2)
    
    print("Pressing Enter to search.")
    d.press("enter")
    human_delay(3)
    
    # --- 3. Select First Result ---
    # We dump and select the first clickable element containing the title
    print("Selecting the best match from results...")
    elements = d(clickable=True)
    found_book = False
    
    for el in elements:
        try:
            text = el.info.get('text', '') or ''
            desc = el.info.get('contentDescription', '') or ''
            
            # Simple heuristic: If it contains part of the title
            # Title might be long or have spaces/subtitles, so we use a substring
            short_title = title.split(' ')[0].split('（')[0]
            
            if short_title in text or short_title in desc:
                print(f"Found match: '{text}' / '{desc}'. Tapping it.")
                el.click()
                found_book = True
                human_delay(4)
                break
        except Exception:
            pass
            
    if not found_book:
        print("Couldn't decisively find the book in the search results list.")
        # Attempt to tap the first general result area as a fallback
        # In WeRead, usually the first result is around bounds (x, 500)
        d.click(1920, 500)
        human_delay(4)

    # --- 4. Enter Reading View ---
    print("Looking for 'id_enterReader' button...")
    read_btn = d(resourceId="id_enterReader")
    if read_btn.exists(timeout=5):
        print("Found reader button. Entering reading view.")
        read_btn.click()
        return True
    
    print("Could not find the 'Read' button. Maybe it's a different variant, or we failed to open the book details.")
    # Fallback to the old method of checking text
    read_text_btn = d(text="阅读")
    if read_text_btn.exists:
        read_text_btn.click()
        return True
        
    return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Open a book in WeRead via uiautomator2.")
    parser.add_argument("title", help="Book title to search for")
    parser.add_argument("--author", default="", help="Author to narrow search")
    args = parser.parse_args()
    
    success = open_book_in_weread(args.title, args.author)
    if success:
        print("SUCCESS")
        sys.exit(0)
    else:
        print("FAILED")
        sys.exit(1)
