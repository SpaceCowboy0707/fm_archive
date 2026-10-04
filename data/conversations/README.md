# Conversation memory

No personal transcripts are included in this repository. Import your own text export using the project environment:

```powershell
./.venv/Scripts/python.exe -X utf8 -m src.import_transcript "path/to/conversation-transcript.txt"
```

The parser expects a header containing the conversation UUID and numbered message blocks delimited by 90 equals signs, `MESSAGE n / total`, `--- BEGIN ORIGINAL CONTENT ---`, and `--- END ORIGINAL CONTENT ---`. Each block includes speaker, message/node IDs, parent node, branch, content type and creation metadata. Arbitrary chat export formats must be converted to this format first.

The original byte stream and previous archive versions are backed up locally. Default chat memory indexes only current-branch visible text; alternate versions stay in the original archive. Image metadata, reasoning/processing recaps and non-text auxiliary nodes are excluded from memory. Source offsets and speaker labels are retained.

Questions receive bounded lexical retrieval. The `story_memory(query, offset)` tool can return additional source-linked excerpts. User statements and assistant suggestions remain historical context, not verified game facts; images cannot be reconstructed from references. Missing timestamps remain missing. Retrieval can miss paraphrases and does not automatically resolve every contradiction.

All originals, backups and the memory database are Git-ignored. Nothing is imported or sent to a model automatically by cloning this repository.
