"""Import a complete text export without executing or rewriting its contents."""
import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from src.conversations import SOURCE

PATTERN = re.compile(r'^={90}\nMESSAGE (\d+) / (\d+)\n(.*?)^--- BEGIN ORIGINAL CONTENT ---\n(.*?)\n--- END ORIGINAL CONTENT ---', re.M | re.S)


def parse(raw):
    text = raw.decode('utf-8-sig').replace('\r\n', '\n')
    identity_match = re.search(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',text[:1500],re.I)
    if not identity_match:
        raise ValueError('Conversation header must include a UUID')
    conversation_id=identity_match.group(0)
    matches = list(PATTERN.finditer(text))
    if not matches:
        raise ValueError('No message boundaries found')
    total = int(matches[0][2])
    if len(matches) != total:
        raise ValueError('Incomplete export: message count mismatch')
    messages, seen = [], set()
    for ordinal, match in enumerate(matches, 1):
        if int(match[1]) != ordinal or int(match[2]) != total:
            raise ValueError('Invalid export sequence')
        meta = dict(line.split(': ', 1) for line in match[3].splitlines() if ': ' in line)
        identity = meta['Message ID']
        if identity in seen or meta['Speaker'] not in ('user', 'assistant'):
            raise ValueError('Duplicate message or unsupported speaker')
        seen.add(identity)
        if meta['Branch'] not in ('CURRENT', 'ALTERNATE'):
            raise ValueError('Unknown conversation branch')
        timestamp = meta.get('Created Unix', 'None')
        messages.append(dict(id=identity, turn_id=meta['Parent node'], role=meta['Speaker'],
            timestamp=None if timestamp == 'None' else float(timestamp), text=match[4],
            branch=meta['Branch'], ordinal=ordinal, metadata=meta))
    branches = Counter(m['branch'] for m in messages)
    return dict(schema_version=1, conversation_id=conversation_id,
        title=messages[0]['metadata']['Conversation title'],
        coverage=dict(status='complete_text_export', message_count=total,
            turn_count=sum(m['role']=='user' and m['branch']=='CURRENT' for m in messages),
            full_history_available=True, current_messages=branches['CURRENT'],
            alternate_messages=branches['ALTERNATE'], attachments_returned=0,
            reason='All nodes declared by the supplied text export are retained, including alternate branches. Image references are preserved; image binaries are not included. Completeness is relative to this supplied export.'),
        import_source=dict(filename='conversation-transcript.txt', sha256=hashlib.sha256(raw).hexdigest(),
            byte_count=len(raw), header=text[:matches[0].start()]), messages=messages)


def import_file(path, destination=SOURCE):
    raw = Path(path).read_bytes()
    data = parse(raw)
    destination = Path(destination)
    imports = destination.parent / 'imports'
    imports.mkdir(parents=True, exist_ok=True)
    digest = data['import_source']['sha256']
    raw_path = imports / (digest + '.txt')
    if raw_path.exists() and raw_path.read_bytes() != raw:
        raise ValueError('Backup checksum collision')
    raw_path.write_bytes(raw)
    if destination.exists():
        previous = destination.read_bytes()
        backup = imports / ('previous-' + hashlib.sha256(previous).hexdigest() + '.json')
        if not backup.exists():
            backup.write_bytes(previous)
    temporary = destination.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(destination)
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path')
    args = parser.parse_args()
    result = import_file(args.path)
    from src.story_memory import rebuild
    print(json.dumps(dict(coverage=result['coverage'], memory=rebuild(result)), ensure_ascii=False))
