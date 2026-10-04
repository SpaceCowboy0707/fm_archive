# Localization

English is the source language for application code, prompts, messages, and repository documentation.

- `zh-CN.json` maps English message IDs to Simplified Chinese UI labels. Template placeholders such as `{0}` must be preserved.
- `input-aliases.json` contains multilingual query keywords and club aliases. These are functional lookup inputs, not display labels.
- The root README is the current English guide. Private historical documentation is not published.

The chat workspace stores its interface language in browser local storage. Native archive pages share that language; optional legacy Streamlit pages have a separate sidebar selector. New requests include the selected response language; saved answers are not rewritten.

Keep database identifiers, tool names, evidence references, imported records, original conversations, and user-authored stories unchanged. Translate display labels rather than stored values. Add new UI translations to the catalog and run `python -m unittest discover -s tests` after changes.
