# Mise

A cooking workflow app that separates recipe prep from cooking execution, built in Streamlit.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the URL Streamlit prints (usually `http://localhost:8501`).

## What's built

- Recipes home with search
- Add Recipe: paste/import a full recipe, or enter it manually
- Recipe detail page
- Mise Mode: prep checklist, grouped by list order, action, or ingredient
- Cooking Mode: one step at a time, large text, next/previous, and a timer when a step mentions a duration
- Grocery list: manual items, or sync ingredients in from any saved recipe, grouped by category
- Settings: units, default view, clear data

Meal planning from the spec isn't built. The spec itself lists it as the first thing to cut if you're simplifying, so I left it out rather than build something half-working.

## How it stores data

Everything saves to `mise_data.json` next to `app.py`. Delete that file to start fresh, or use "Clear all data" in Settings.

## Where the parsing is rough

Turning "2 cups onions, chopped" into "Chop 2 cups onions" is done with regex and a small dictionary of past-tense verbs (chopped, diced, minced, and so on). It handles standard recipe phrasing well. It will not handle everything: unusual phrasing, uncommon units, or ingredients with multiple clauses may parse imperfectly. When that happens, open the recipe's Edit page and adjust the ingredient or step lines directly, or just live with the raw text.

The "paste a whole recipe" import looks for lines that say "Ingredients" and "Steps"/"Instructions"/"Directions" to split the sections. If your source doesn't have those headers, everything after the title gets treated as steps, and you'll want to fix it up in Manual Entry or Edit.

## Timers

When a cooking step mentions a duration ("cook for 5 minutes"), a Start Timer button appears. The countdown runs in the browser via JavaScript, not through Streamlit's own state, so it won't survive a page refresh and it can't trigger a server-side alert. It's there to glance at, not to replace a kitchen timer if you're walking away from the screen.
