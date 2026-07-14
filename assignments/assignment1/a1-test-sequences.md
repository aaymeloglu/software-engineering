# A1 BBS - Test Sequences

Manual command sequences that exercise edge cases. Each sequence starts from a clean state (delete `bbs.json` and `bbs.db` before running).

---

## Sequence 1: Basic round-trip

The happy path. If this doesn't work, nothing does.

```bash
rm -f bbs.json bbs.db

python bbs.py post alice "First post!"
python bbs.py post bob "Welcome alice"
python bbs.py post alice "Thanks bob"
python bbs.py read
python bbs.py users
python bbs.py search "alice"
```

**Expected:**
- `read` shows 3 posts in chronological order
- `users` shows `alice` and `bob` (2 users, not 3 -- alice posted twice)
- `search "alice"` matches the two posts containing "alice" (bob's message mentions her)

---

## Sequence 2: Same username, many posts

Tests that migration deduplicates users correctly.

```bash
rm -f bbs.json bbs.db

python bbs.py post dave "Message one"
python bbs.py post dave "Message two"
python bbs.py post dave "Message three"
python bbs.py post dave "Message four"
python bbs.py post dave "Message five"
python bbs.py users
```

**Expected:**
- `users` shows exactly one entry: `dave`

**Then migrate:**
```bash
python migrate.py
python bbs_db.py users
python bbs_db.py read
```

**Expected:**
- `users` still shows exactly one `dave` (not five)
- `read` shows all 5 posts in order
- The `users` table in SQLite should have exactly 1 row

**Verify directly:**
```bash
sqlite3 bbs.db "SELECT COUNT(*) FROM users;"
# Should print: 1
sqlite3 bbs.db "SELECT COUNT(*) FROM posts;"
# Should print: 5
```

---

## Sequence 3: Search case sensitivity

The assignment doesn't specify case behavior, but it's worth seeing what they chose.

```bash
rm -f bbs.json bbs.db

python bbs.py post alice "Python is great"
python bbs.py post bob "I love PYTHON too"
python bbs.py post carol "java is fine I guess"

python bbs.py search "Python"
python bbs.py search "python"
python bbs.py search "PYTHON"
```

**Interesting because:** SQLite `LIKE` is case-insensitive for ASCII by default. A naive Python implementation (`if keyword in message`) is case-sensitive. So after migration, the same search might return different results in the JSON version vs the SQL version. This is exactly the kind of thing the README comparison should address.

---

## Sequence 4: Special characters in messages

```bash
rm -f bbs.json bbs.db

python bbs.py post alice 'She said "hello"'
python bbs.py post bob "It's a beautiful day"
python bbs.py post carol "Price is $5.00 (50% off!)"
python bbs.py post dave "backslash: \ and tab:	done"
python bbs.py post eve '{"username": "fake", "message": "injected"}'

python bbs.py read
cat bbs.json
```

**Interesting because:**
- Quotes inside messages can break naive JSON serialization if they're hand-building strings instead of using `json.dumps`
- The last post is a JSON string as a message -- does it survive a round-trip through `bbs.json` without corrupting the file structure?
- After migration, do all these posts survive intact in SQLite?

```bash
python migrate.py
python bbs_db.py read
```

**Expected:** Both `read` commands produce identical output.

---

## Sequence 5: SQL injection attempt

```bash
rm -f bbs.db

python bbs_db.py post alice "Normal post"
python bbs_db.py post "Robert'; DROP TABLE posts;--" "Oh no"
python bbs_db.py search "'; DROP TABLE posts;--"
python bbs_db.py read
```

**Expected:** Nothing breaks. Both the username and the search term should be handled safely via parameterized queries. The post by `Robert'; DROP TABLE posts;--` should just show up as a normal post from a user with a weird name.

---

## Sequence 6: Empty / edge-case states

```bash
rm -f bbs.json bbs.db

# Read from empty board
python bbs.py read
python bbs.py users
python bbs.py search "anything"

# Search with no matches
python bbs.py post alice "Hello world"
python bbs.py search "xyzzy"

# Migrate empty JSON to SQLite
rm -f bbs.json bbs.db
echo "[]" > bbs.json
python migrate.py
python bbs_db.py read
```

**Interesting because:** Many implementations crash on empty state -- `FileNotFoundError` on first `read`, or `json.decoder.JSONDecodeError` if `bbs.json` doesn't exist yet. The empty-array migration tests whether `migrate.py` handles the degenerate case.

---

## Sequence 7: Migration idempotency

What happens when you run migrate twice?

```bash
rm -f bbs.json bbs.db

python bbs.py post alice "Hello"
python bbs.py post bob "World"

python migrate.py
python migrate.py

python bbs_db.py read
sqlite3 bbs.db "SELECT COUNT(*) FROM posts;"
```

**Interesting because:** If the migration doesn't handle pre-existing data, you'll get either:
- Duplicate posts (4 instead of 2)
- A unique constraint violation crash on usernames
- Or it works cleanly (they explicitly handled it)

The assignment asks them to document this choice in the README. This sequence tests whether what they documented matches what actually happens.

---

## Sequence 8: Timestamps survive migration

```bash
rm -f bbs.json bbs.db

python bbs.py post alice "Morning post"
sleep 2
python bbs.py post bob "Afternoon post"

python bbs.py read > /tmp/json_output.txt

python migrate.py
python bbs_db.py read > /tmp/db_output.txt

diff /tmp/json_output.txt /tmp/db_output.txt
```

**Expected:** The diff should be empty. If timestamps are regenerated during migration instead of preserved from JSON, the times will differ. This is a common agent mistake -- the migration inserts posts with `datetime.now()` instead of reading the timestamp from the JSON record.

---

## Sequence 9: Large-ish dataset for search comparison

```bash
rm -f bbs.json bbs.db

# Generate 100 posts
for i in $(seq 1 100); do
  python bbs.py post "user$((i % 7))" "Post number $i about topic $((i % 3))"
done

python bbs.py search "topic 0"
python bbs.py users

python migrate.py
python bbs_db.py search "topic 0"
python bbs_db.py users
```

**Interesting because:** 
- 100 posts from 7 cycling users -- migration must deduplicate to exactly 7 user rows
- Search results should match between JSON and SQL versions
- Not huge, but enough to notice if something is O(n^2) or re-reading the file per post

---

## Sequence 10: Posts with the search keyword in the username (not message)

```bash
rm -f bbs.json bbs.db

python bbs.py post hello "Goodbye world"
python bbs.py post world "Hello everyone"

python bbs.py search "hello"
```

**Interesting because:** Should `search` match usernames, or only message bodies? The spec says "search posts by keyword" and the SQL example only checks `WHERE p.message LIKE :keyword`. But in the JSON version, students might accidentally search the whole record. If username "hello" shows up in JSON search but not SQL search, that's a discrepancy the README should catch.
