# Manual story format

Create `data/manual/lore.json` locally. This file is Git-ignored. Example (entirely fictional):

```json
{
  "schema_version": 1,
  "entries": [
    {
      "id": "example-welcome",
      "level": "headcanon",
      "title": "Welcoming the new teammate",
      "text": "The captain offers to show a new teammate around the training ground.",
      "source": "User-created fictional example",
      "season": "2035/36",
      "player_keys": [],
      "player_names": []
    }
  ]
}
```

Every entry requires a unique ID, title, text and source. Allowed evidence levels are `canon`, `inferred` and `headcanon`. `canon` must have an independently supported game source; an old assistant saying something happened is not sufficient. Use exact player names or stable identity keys when available. Save imports preserve this manual layer. Explicitly collected website stories are stored separately in the local chat database.
