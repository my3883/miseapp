"""
Mise - recipe box, meal planning, and shopping list, built in Streamlit.

Run with:
    streamlit run app.py
"""

import json
import os
import re
import uuid
from datetime import date, datetime, timedelta

import streamlit as st

# ---------------------------------------------------------------------------
# Constants and small helpers
# ---------------------------------------------------------------------------

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mise_data.json")

UNITS = {
    "cup", "cups", "tbsp", "tbsps", "tablespoon", "tablespoons",
    "tsp", "tsps", "teaspoon", "teaspoons", "oz", "ounce", "ounces",
    "lb", "lbs", "pound", "pounds", "g", "gram", "grams", "kg",
    "kilogram", "kilograms", "ml", "milliliter", "milliliters",
    "l", "liter", "liters", "clove", "cloves", "pinch", "pinches",
    "can", "cans", "slice", "slices", "stick", "sticks", "bunch",
    "bunches", "head", "heads",
}

GROCERY_CATEGORIES = ["Produce", "Dairy", "Meat & Seafood", "Pantry", "Frozen", "Other"]

CATEGORY_HINTS = {
    "Produce": ["onion", "garlic", "tomato", "pepper", "lettuce", "spinach", "carrot",
                "potato", "lemon", "lime", "herb", "basil", "cilantro", "parsley",
                "apple", "avocado", "cucumber", "broccoli", "mushroom", "ginger"],
    "Dairy": ["milk", "cheese", "butter", "cream", "yogurt", "egg"],
    "Meat & Seafood": ["chicken", "beef", "pork", "fish", "shrimp", "salmon", "bacon",
                        "sausage", "turkey"],
    "Frozen": ["frozen"],
    "Pantry": ["flour", "sugar", "salt", "oil", "rice", "pasta", "beans", "broth",
               "stock", "vinegar", "sauce", "spice", "baking"],
}


def new_id():
    return str(uuid.uuid4())[:8]


def guess_category(name):
    name_l = name.lower()
    for cat, hints in CATEGORY_HINTS.items():
        if any(h in name_l for h in hints):
            return cat
    return "Other"


def parse_ingredient_line(line):
    """Pull qty / unit / name out of a single ingredient line, e.g.
    '2 cups onions, chopped' -> qty '2', unit 'cups', name 'onions, chopped'.
    """
    raw = line.strip()
    if not raw:
        return None

    text_wo_paren = re.sub(r"\([^)]*\)", "", raw).strip()
    main = text_wo_paren.split(",")[0].strip()

    qty_match = re.match(r"^\s*((?:\d+\s+)?\d+/\d+|\d*\.\d+|\d+)\s*(.*)$", main)
    qty = ""
    rest = main
    if qty_match and qty_match.group(1):
        qty = qty_match.group(1).strip()
        rest = qty_match.group(2).strip()

    unit = ""
    name = rest
    words = rest.split(" ", 1)
    if words and words[0].lower().strip(".") in UNITS:
        unit = words[0]
        name = words[1] if len(words) > 1 else ""

    trailing = ",".join(text_wo_paren.split(",")[1:]).strip()
    display_name = (name.strip() + (", " + trailing if trailing else "")).strip()

    return {
        "id": new_id(),
        "raw": raw,
        "qty": qty,
        "unit": unit,
        "name": (name.strip() or display_name),
        "display_name": display_name or name.strip(),
        "done": False,
    }


def parse_ingredients_text(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    result = []
    for l in lines:
        parsed = parse_ingredient_line(l)
        if parsed:
            result.append(parsed)
    return result


def parse_steps_text(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    steps = []
    for l in lines:
        cleaned = re.sub(r"^\s*\d+[\.\)]\s*", "", l)
        steps.append({"id": new_id(), "raw": cleaned, "done": False})
    return steps


def naive_recipe_parse(blob):
    """
    Lightweight parser for pasted / imported recipe text. Looks for
    'Ingredients' and 'Steps'/'Instructions' section headers. Falls back to
    treating the whole thing as steps if no headers are found.
    """
    title = "Untitled Recipe"
    lines = blob.strip().split("\n")
    if lines:
        title = lines[0].strip()[:120] or title

    ing_section = ""
    step_section = ""

    ing_idx = None
    step_idx = None
    for i, l in enumerate(lines):
        l_low = l.strip().lower().strip(":")
        if l_low in ("ingredients",):
            ing_idx = i
        if l_low in ("steps", "instructions", "directions", "method"):
            step_idx = i

    if ing_idx is not None and step_idx is not None:
        ing_section = "\n".join(lines[ing_idx + 1:step_idx])
        step_section = "\n".join(lines[step_idx + 1:])
    elif ing_idx is not None:
        ing_section = "\n".join(lines[ing_idx + 1:])
    elif step_idx is not None:
        step_section = "\n".join(lines[step_idx + 1:])
        ing_section = "\n".join(lines[1:ing_idx if ing_idx else step_idx])
    else:
        step_section = "\n".join(lines[1:])

    return {
        "title": title,
        "ingredients": parse_ingredients_text(ing_section),
        "steps": parse_steps_text(step_section),
    }


def parse_recipe_from_url(url):
    """
    Fetch a recipe page and extract title / ingredients / steps.

    Uses the recipe-scrapers library, which has purpose-built parsers for
    hundreds of recipe sites and falls back to generic schema.org recipe
    markup for everything else. Raises RuntimeError with a plain-language
    message on any failure, so the UI can just show it.
    """
    try:
        import requests
    except ImportError:
        raise RuntimeError("The 'requests' package isn't installed. Run: pip install -r requirements.txt")
    try:
        from recipe_scrapers import scrape_html
    except ImportError:
        raise RuntimeError("The 'recipe-scrapers' package isn't installed. Run: pip install -r requirements.txt")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
        "Upgrade-Insecure-Requests": "1",
    }
    try:
        session = requests.Session()
        resp = session.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status in (403, 429, 401):
            raise RuntimeError(
                "This site is blocking automated requests (it's not a parsing "
                "problem, it's the site actively saying no). Some large "
                "publishers do this regardless of what headers a script sends. "
                "Use Paste / Import instead: open the page yourself, copy the "
                "ingredients and steps, and paste them there."
            )
        raise RuntimeError(f"Couldn't reach that page: {e}")
    except Exception as e:
        raise RuntimeError(f"Couldn't reach that page: {e}")

    try:
        scraper = scrape_html(resp.text, org_url=url, supported_only=False)
    except Exception:
        raise RuntimeError(
            "Couldn't find recipe data on that page. Some sites don't mark up "
            "their recipe in a format this can read. Try Paste / Import "
            "instead: copy the recipe text and paste it there."
        )

    def safe(fn, default=None):
        try:
            val = fn()
            return val if val else default
        except Exception:
            return default

    title = safe(scraper.title, "Untitled Recipe")
    ingredients_raw = safe(scraper.ingredients, []) or []
    instructions_raw = safe(scraper.instructions, "") or ""
    total_time = safe(scraper.total_time)
    yields = safe(scraper.yields, "")

    ingredients = [parse_ingredient_line(l) for l in ingredients_raw if l and l.strip()]
    ingredients = [i for i in ingredients if i]
    steps = parse_steps_text(instructions_raw)

    return {
        "title": (title or "Untitled Recipe").strip(),
        "servings": (yields or "").strip(),
        "prep_time": "",
        "cook_time": f"{total_time} min" if total_time else "",
        "ingredients": ingredients,
        "steps": steps,
        "source_url": url,
    }


# ---------------------------------------------------------------------------
# Meal plan date helpers
# ---------------------------------------------------------------------------

def week_dates(start_monday):
    return [start_monday + timedelta(days=i) for i in range(7)]


def this_and_next_week():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return week_dates(monday), week_dates(monday + timedelta(days=7))


def format_day_label(d):
    today = date.today()
    prefix = "Today · " if d == today else ""
    return f"{prefix}{d.strftime('%a, %b')} {d.day}"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "recipes": {},
        "grocery": [],
        "meal_plan": {},
        "settings": {"units": "imperial"},
    }


def save_data():
    payload = {
        "recipes": st.session_state.recipes,
        "grocery": st.session_state.grocery,
        "meal_plan": st.session_state.meal_plan,
        "settings": st.session_state.settings,
    }
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(payload, f, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------

def init_state():
    if "initialized" in st.session_state:
        return
    data = load_data()
    st.session_state.recipes = data.get("recipes", {})
    st.session_state.grocery = data.get("grocery", [])
    st.session_state.meal_plan = data.get("meal_plan", {})
    st.session_state.settings = data.get("settings", {"units": "imperial"})
    st.session_state.page = "home"
    st.session_state.current_id = None
    st.session_state.initialized = True


def goto(page, recipe_id=None):
    st.session_state.page = page
    if recipe_id is not None:
        st.session_state.current_id = recipe_id


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

def inject_css():
    st.markdown(
        """
        <style>
        .stButton > button {
            font-size: 1.0rem;
            padding: 0.55rem 1rem;
            border-radius: 10px;
            width: 100%;
        }
        .mise-card {
            border: 1px solid rgba(128,128,128,0.25);
            border-radius: 12px;
            padding: 0.9rem 1rem;
            margin-bottom: 0.6rem;
        }
        .mise-title {
            font-size: 1.15rem;
            font-weight: 700;
            margin-bottom: 0.15rem;
        }
        .mise-meta {
            color: #888;
            font-size: 0.9rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def page_home():
    st.title("Mise")
    st.caption("Your recipes, meal plan, and shopping list.")

    search = st.text_input("Search recipes", placeholder="Search by title or tag", label_visibility="collapsed")

    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("+ Add Recipe"):
            goto("add")

    recipes = list(st.session_state.recipes.values())
    if search:
        s_low = search.lower()
        recipes = [
            r for r in recipes
            if s_low in r["title"].lower() or any(s_low in t.lower() for t in r.get("tags", []))
        ]

    if not recipes:
        st.info("No recipes yet. Tap **Add Recipe** to get started.")
        return

    recipes.sort(key=lambda r: r.get("created_at", ""), reverse=True)

    for r in recipes:
        with st.container():
            st.markdown('<div class="mise-card">', unsafe_allow_html=True)
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f'<div class="mise-title">{r["title"]}</div>', unsafe_allow_html=True)
                meta_bits = []
                if r.get("servings"):
                    meta_bits.append(f"Serves {r['servings']}")
                if r.get("prep_time"):
                    meta_bits.append(f"Prep {r['prep_time']}")
                if r.get("cook_time"):
                    meta_bits.append(f"Cook {r['cook_time']}")
                if r.get("tags"):
                    meta_bits.append(", ".join(r["tags"]))
                if meta_bits:
                    st.markdown(f'<div class="mise-meta">{" · ".join(meta_bits)}</div>', unsafe_allow_html=True)
            with c2:
                if st.button("Open", key=f"open_{r['id']}"):
                    goto("detail", r["id"])
            st.markdown("</div>", unsafe_allow_html=True)


def page_add():
    st.title("Add Recipe")
    if st.button("← Back"):
        goto("home")

    tab_url, tab_paste, tab_manual = st.tabs(["From URL", "Paste / Import", "Manual Entry"])

    with tab_url:
        st.caption(
            "Paste a link to a recipe page. Works best on recipe blogs and food "
            "sites, since most of them mark up their ingredients and steps in a "
            "standard format behind the scenes. A few large publishers "
            "(Food Network, NYT Cooking) actively block this, use Paste / "
            "Import for those."
        )
        url = st.text_input("Recipe URL", key="url_input", placeholder="https://www.example.com/some-recipe")
        if st.button("Import from URL", key="import_url_btn"):
            if not url.strip():
                st.warning("Paste a URL first.")
            else:
                with st.spinner("Reading the recipe..."):
                    try:
                        parsed = parse_recipe_from_url(url.strip())
                        error = None
                    except RuntimeError as e:
                        parsed = None
                        error = str(e)
                if error:
                    st.error(error)
                elif parsed:
                    rid = new_id()
                    recipe = {
                        "id": rid,
                        "title": parsed["title"],
                        "servings": parsed["servings"],
                        "prep_time": parsed["prep_time"],
                        "cook_time": parsed["cook_time"],
                        "tags": [],
                        "ingredients": parsed["ingredients"],
                        "steps": parsed["steps"],
                        "source_url": parsed.get("source_url", ""),
                        "created_at": datetime.now().isoformat(),
                    }
                    st.session_state.recipes[rid] = recipe
                    save_data()
                    if not parsed["ingredients"] and not parsed["steps"]:
                        st.warning(
                            "Found the page but couldn't pull out ingredients or steps. "
                            "You can add them on the Edit page now."
                        )
                    goto("detail", rid)
                    st.rerun()

    with tab_paste:
        st.caption("Paste a full recipe (title on the first line, then Ingredients / Steps sections if you have them).")
        blob = st.text_area("Recipe text", height=280, key="paste_blob")
        if st.button("Parse Recipe", key="parse_btn"):
            if not blob.strip():
                st.warning("Paste some recipe text first.")
            else:
                parsed = naive_recipe_parse(blob)
                rid = new_id()
                recipe = {
                    "id": rid,
                    "title": parsed["title"],
                    "servings": "",
                    "prep_time": "",
                    "cook_time": "",
                    "tags": [],
                    "ingredients": parsed["ingredients"],
                    "steps": parsed["steps"],
                    "source_url": "",
                    "created_at": datetime.now().isoformat(),
                }
                st.session_state.recipes[rid] = recipe
                save_data()
                if not parsed["ingredients"] and not parsed["steps"]:
                    st.warning("Couldn't find clear ingredients or steps. You can edit the recipe manually now.")
                goto("detail", rid)
                st.rerun()

    with tab_manual:
        title = st.text_input("Title", key="manual_title")
        c1, c2, c3 = st.columns(3)
        with c1:
            servings = st.text_input("Servings", key="manual_servings")
        with c2:
            prep_time = st.text_input("Prep time", key="manual_prep")
        with c3:
            cook_time = st.text_input("Cook time", key="manual_cook")
        tags_raw = st.text_input("Tags (comma separated)", key="manual_tags")
        ing_text = st.text_area(
            "Ingredients (one per line)",
            placeholder="2 cups onions, chopped\n1 tbsp olive oil\n3 cloves garlic, minced",
            height=150,
            key="manual_ing",
        )
        steps_text = st.text_area(
            "Steps (one per line, in order)",
            placeholder="Heat oil in a pan over medium heat\nAdd onions and cook 5 minutes\nAdd garlic and cook 1 minute",
            height=150,
            key="manual_steps",
        )
        if st.button("Save Recipe", key="save_manual"):
            if not title.strip():
                st.warning("Give the recipe a title.")
            else:
                rid = new_id()
                recipe = {
                    "id": rid,
                    "title": title.strip(),
                    "servings": servings.strip(),
                    "prep_time": prep_time.strip(),
                    "cook_time": cook_time.strip(),
                    "tags": [t.strip() for t in tags_raw.split(",") if t.strip()],
                    "ingredients": parse_ingredients_text(ing_text),
                    "steps": parse_steps_text(steps_text),
                    "source_url": "",
                    "created_at": datetime.now().isoformat(),
                }
                st.session_state.recipes[rid] = recipe
                save_data()
                goto("detail", rid)
                st.rerun()


def get_current_recipe():
    rid = st.session_state.current_id
    return st.session_state.recipes.get(rid) if rid else None


def page_detail():
    recipe = get_current_recipe()
    if not recipe:
        st.warning("Recipe not found.")
        goto("home")
        return

    if st.button("← All Recipes"):
        goto("home")

    st.title(recipe["title"])
    meta_bits = []
    if recipe.get("servings"):
        meta_bits.append(f"Serves {recipe['servings']}")
    if recipe.get("prep_time"):
        meta_bits.append(f"Prep {recipe['prep_time']}")
    if recipe.get("cook_time"):
        meta_bits.append(f"Cook {recipe['cook_time']}")
    if meta_bits:
        st.caption(" · ".join(meta_bits))
    if recipe.get("source_url"):
        st.caption(f"Source: {recipe['source_url']}")

    st.subheader("Ingredients")
    if recipe["ingredients"]:
        for ing in recipe["ingredients"]:
            bits = [ing["qty"], ing["unit"], ing.get("display_name") or ing["name"] or ing["raw"]]
            st.markdown("- " + " ".join(b for b in bits if b))
    else:
        st.caption("No ingredients recorded.")

    st.subheader("Steps")
    if recipe["steps"]:
        for i, step in enumerate(recipe["steps"], 1):
            st.markdown(f"{i}. {step['raw']}")
    else:
        st.caption("No steps recorded.")

    st.divider()
    st.subheader("Add to Meal Plan")
    pick_date = st.date_input("Day", value=date.today(), key="detail_meal_date")
    if st.button("Add to this day"):
        key = pick_date.isoformat()
        st.session_state.meal_plan.setdefault(key, []).append(recipe["id"])
        save_data()
        st.success(f"Added to {format_day_label(pick_date)}")

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Edit Recipe", key="edit_recipe"):
            goto("edit")
    with c2:
        if st.button("Delete Recipe", key="delete_recipe"):
            del st.session_state.recipes[recipe["id"]]
            save_data()
            goto("home")
            st.rerun()


def page_edit():
    recipe = get_current_recipe()
    if not recipe:
        goto("home")
        return

    st.title(f"Edit: {recipe['title']}")
    if st.button("← Cancel"):
        goto("detail")
        st.rerun()

    title = st.text_input("Title", value=recipe["title"])
    c1, c2, c3 = st.columns(3)
    with c1:
        servings = st.text_input("Servings", value=recipe.get("servings", ""))
    with c2:
        prep_time = st.text_input("Prep time", value=recipe.get("prep_time", ""))
    with c3:
        cook_time = st.text_input("Cook time", value=recipe.get("cook_time", ""))
    tags_raw = st.text_input("Tags (comma separated)", value=", ".join(recipe.get("tags", [])))

    ing_lines = "\n".join(i["raw"] for i in recipe["ingredients"])
    ing_text = st.text_area("Ingredients (one per line)", value=ing_lines, height=150)

    step_lines = "\n".join(s["raw"] for s in recipe["steps"])
    steps_text = st.text_area("Steps (one per line)", value=step_lines, height=150)

    if st.button("Save Changes"):
        recipe["title"] = title.strip() or recipe["title"]
        recipe["servings"] = servings.strip()
        recipe["prep_time"] = prep_time.strip()
        recipe["cook_time"] = cook_time.strip()
        recipe["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]
        recipe["ingredients"] = parse_ingredients_text(ing_text)
        recipe["steps"] = parse_steps_text(steps_text)
        save_data()
        goto("detail")
        st.rerun()


def page_meal_plan():
    st.title("Meal Plan")
    st.caption("Assign recipes to days across this week and next.")

    recipe_options = {r["title"]: r["id"] for r in st.session_state.recipes.values()}
    this_week, next_week = this_and_next_week()

    if not recipe_options:
        st.info("Add a recipe first, then come back here to plan your week.")

    for label, week in [("This Week", this_week), ("Next Week", next_week)]:
        st.subheader(label)
        for d in week:
            date_key = d.isoformat()
            assigned = st.session_state.meal_plan.get(date_key, [])
            names = [
                st.session_state.recipes[rid]["title"]
                for rid in assigned
                if rid in st.session_state.recipes
            ]
            summary = ", ".join(names) if names else "No meals planned"
            with st.expander(f"{format_day_label(d)} — {summary}"):
                for idx, rid in enumerate(assigned):
                    r = st.session_state.recipes.get(rid)
                    if not r:
                        continue
                    c1, c2 = st.columns([5, 1])
                    with c1:
                        st.write(r["title"])
                    with c2:
                        if st.button("Remove", key=f"rm_{date_key}_{idx}"):
                            st.session_state.meal_plan[date_key].pop(idx)
                            save_data()
                            st.rerun()
                if recipe_options:
                    sel = st.selectbox(
                        "Add a recipe",
                        ["— choose —"] + list(recipe_options.keys()),
                        key=f"sel_{date_key}",
                    )
                    if st.button("Add", key=f"add_{date_key}"):
                        if sel != "— choose —":
                            st.session_state.meal_plan.setdefault(date_key, []).append(recipe_options[sel])
                            save_data()
                            st.rerun()


def page_shopping():
    st.title("Shopping List")

    with st.expander("Add item by hand"):
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            item_name = st.text_input("Item", key="grocery_new_name")
        with c2:
            item_qty = st.text_input("Qty", key="grocery_new_qty")
        with c3:
            item_cat = st.selectbox("Category", GROCERY_CATEGORIES, key="grocery_new_cat")
        if st.button("Add to list"):
            if item_name.strip():
                st.session_state.grocery.append({
                    "id": new_id(),
                    "name": item_name.strip(),
                    "qty": item_qty.strip(),
                    "category": item_cat,
                    "checked": False,
                })
                save_data()
                st.rerun()

    st.subheader("Build from Meal Plan")
    this_week, next_week = this_and_next_week()
    c1, c2 = st.columns(2)
    with c1:
        use_this = st.checkbox("This week", value=True, key="sync_this_week")
    with c2:
        use_next = st.checkbox("Next week", value=False, key="sync_next_week")

    if st.button("Sync ingredients from planned days"):
        dates = []
        if use_this:
            dates += this_week
        if use_next:
            dates += next_week
        recipe_ids = []
        for d in dates:
            recipe_ids.extend(st.session_state.meal_plan.get(d.isoformat(), []))

        if not recipe_ids:
            st.warning("No recipes are assigned to the selected week(s) yet. Add some in Meal Plan first.")
        else:
            for rid in recipe_ids:
                recipe = st.session_state.recipes.get(rid)
                if not recipe:
                    continue
                for ing in recipe["ingredients"]:
                    name = ing.get("name") or ing["raw"]
                    if not name:
                        continue
                    existing = next(
                        (g for g in st.session_state.grocery if g["name"].lower() == name.lower()),
                        None,
                    )
                    qty_bits = " ".join(b for b in [ing["qty"], ing["unit"]] if b)
                    if existing:
                        if qty_bits:
                            existing["qty"] = (existing["qty"] + " + " if existing["qty"] else "") + qty_bits
                    else:
                        st.session_state.grocery.append({
                            "id": new_id(),
                            "name": name,
                            "qty": qty_bits,
                            "category": guess_category(name),
                            "checked": False,
                        })
            save_data()
            st.success(f"Synced ingredients from {len(recipe_ids)} planned meal(s).")
            st.rerun()

    st.divider()

    if not st.session_state.grocery:
        st.info("Your shopping list is empty.")
        return

    if st.button("Clear completed"):
        st.session_state.grocery = [g for g in st.session_state.grocery if not g["checked"]]
        save_data()
        st.rerun()

    for cat in GROCERY_CATEGORIES:
        items = [g for g in st.session_state.grocery if g["category"] == cat]
        if not items:
            continue
        st.markdown(f"**{cat}**")
        for item in items:
            c1, c2 = st.columns([5, 1])
            with c1:
                label = item["name"] + (f" — {item['qty']}" if item["qty"] else "")
                checked = st.checkbox(label, value=item["checked"], key=f"grocery_{item['id']}")
                if checked != item["checked"]:
                    item["checked"] = checked
                    save_data()
                    st.rerun()
            with c2:
                if st.button("Remove", key=f"remove_{item['id']}"):
                    st.session_state.grocery = [g for g in st.session_state.grocery if g["id"] != item["id"]]
                    save_data()
                    st.rerun()


def page_settings():
    st.title("Settings")

    units = st.radio(
        "Units",
        ["imperial", "metric"],
        index=0 if st.session_state.settings.get("units", "imperial") == "imperial" else 1,
        format_func=lambda x: "Imperial (cups, oz, lb)" if x == "imperial" else "Metric (g, ml, kg)",
    )
    if units != st.session_state.settings.get("units"):
        st.session_state.settings["units"] = units
        save_data()

    st.divider()
    st.caption(f"Data is stored locally at: `{DATA_FILE}`")
    if st.button("Clear all data", type="secondary"):
        st.session_state.recipes = {}
        st.session_state.grocery = []
        st.session_state.meal_plan = {}
        save_data()
        st.success("Cleared.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Mise", page_icon="🔪", layout="centered")
    init_state()
    inject_css()

    with st.sidebar:
        st.markdown("### Mise")
        if st.button("🍽 Recipes", use_container_width=True):
            goto("home")
        if st.button("📅 Meal Plan", use_container_width=True):
            goto("meal_plan")
        if st.button("🛒 Shopping List", use_container_width=True):
            goto("shopping")
        if st.button("⚙️ Settings", use_container_width=True):
            goto("settings")

    page = st.session_state.page
    if page == "home":
        page_home()
    elif page == "add":
        page_add()
    elif page == "detail":
        page_detail()
    elif page == "edit":
        page_edit()
    elif page == "meal_plan":
        page_meal_plan()
    elif page == "shopping":
        page_shopping()
    elif page == "settings":
        page_settings()
    else:
        page_home()


if __name__ == "__main__":
    main()
