# Recording the demo video on the office laptop

Target: one MP4, 4–5 minutes, under 50 MB (the portal's limit per file).
Total time needed: about 2 hours. Most of it is one unattended run.

---

## 0. Bring from the home laptop (USB or OneDrive, not chat or email)

1. `C:\Users\adity\Downloads\nimo-cache-2026-09-23.zip` (678 MB)
2. `C:\Users\adity\Downloads\NIMO\.env`

---

## 1. Set up (15 minutes)

Connect to the NIQ network or VPN first: the model only works there.

Open PowerShell in the NIMO folder:

```powershell
git pull
uv sync
```

1. Copy `.env` into the NIMO folder, next to `README.md`. It must contain
   `CIS_LLM_API_KEY=`, `BRAVE_API_KEY=` and `SEARXNG_BASE_URL=http://localhost:8080`.
2. Delete the old `data\cache` folder if one exists.
3. Unzip `nimo-cache-2026-09-23.zip` **into the NIMO folder**. Check:
   `dir data\cache` must list `images`, `llm`, `pages`, `search`.
   (Not `data\cache\data\cache\...`. If Windows made an extra folder, move
   the four folders up.)

---

## 2. Three checks (2 minutes)

```powershell
uv run python -m nimo.llm --ping
uv run python -m nimo.llm --ping-image
uv run python -m nimo.retrieval --ping
```

| Check | Good result | If it fails |
|---|---|---|
| `nimo.llm --ping` | `call     : OK  ok=True ...` | VPN not connected, or `CIS_LLM_API_KEY` wrong in `.env` |
| `nimo.llm --ping-image` | `image    : OK  colour='red' ... (as expected)` | set `use_image_evidence: false` in `config\characteristics.yaml` and carry on |
| `nimo.retrieval --ping` | `OK: Brave Search API answered 5 results` | certificate error: add `NIMO_SYSTEM_CERTS=1` to `.env` and retry. Still failing: skip scene 6 below |

---

## 3. Produce the final output (about 1 hour, unattended, before recording)

```powershell
uv run python -m nimo.run --sheet qa --live --characteristics --out-dir data\out\final
```

At the end it prints a summary. Check:
- `rows: 412  succeeded: 412`. If some failed, run the same command again. It resumes.
- `search backend: Brave Search API — 0 paid call(s)` (or close to 0). If the
  paid count climbs past ~10 while it runs, the cache is not in the right
  place: press **Ctrl+C**, fix step 1.3, run again.

Then:

```powershell
uv run python -m nimo.assemble --sheet qa --out-dir data\out\final
uv run python -m nimo.site --sheet qa --out-dir data\out\final --title "NIMO — The Product Truth Agent"
```

You now have:
- `data\out\final\submission_qa.xlsx`: the file NIMO generates for submission
- `data\out\final\site_qa.html`: the results page

Do **not** start the UI while this run is going. Both write the product
registry.

---

## 4. Rehearse once (10 minutes)

This fills the model's cache, so nothing makes you wait on camera.

```powershell
uv run python -m nimo.ui --live --characteristics
```

Open **http://127.0.0.1:8765** in Edge or Chrome. Leave PowerShell running.

1. In **DATASET ROWS**, click `qa:0` → **Run**. Wait for the card.
2. Type `green people` in the filter box → click `qa:28` → **Run**.
3. Click `qa:9` → **Run**. The registry line should say `tier0_exact`.
4. In **TRY ANY PRODUCT**, type:
   - description: `parla toothpaste tablets pro 62`
   - brand: `PARLA`
   - barcode: `5060758650044`
   - press **Resolve**. It should come back almost instantly as `tier0_exact`.
     This is scene 5.
5. Optional, for scene 6 (2–4 Brave credits):
   - description: `listerine total care stain remover mouthwash 500ml`
   - brand: `LISTERINE (KENVUE)`
   - press **Resolve**. It takes about a minute. Look at the result: if the
     chosen page is clearly not Listerine, leave scene 6 out.

Click through each once more. Every second click is instant.

---

## 5. Recording setup (5 minutes)

**Tool:** use whichever works on the office laptop.
- **Snipping Tool** (Windows 11): `Win + Shift + R`, drag over the screen,
  turn the microphone on, then Start. It saves an MP4.
- **Clipchamp** (preinstalled): Record & create → Screen and camera.
- **Teams:** start a meeting with only yourself, share your screen, click
  Record. Download the MP4 from the chat afterwards.

**Screen:**
- Turn on Do not disturb (Windows notifications, Teams, Outlook).
- Close everything except PowerShell, the browser, Excel and PowerPoint.
- Browser: press F11 for full screen and zoom to 110%.
- PowerShell: make the font bigger (Ctrl + mouse wheel).
- **Never open `.env` on screen.** It contains the API keys.

**Sound:** use a headset mic in a quiet room. Do a 10-second test recording and play it back.

---

## 6. The script (about 5 minutes)

Speak slowly. Pause for a second after each click. Mistakes are fine: stop
and redo that scene, then cut it afterwards.

### Scene 1: Introduction (30 s). Show deck slide 1, then slide 4
> "This is NIMO, our Product Truth Agent. Give it a retail product record
> (a description, brand and barcode) and it finds the web page that really is
> that product, identifies its module, fills in the characteristics that
> apply, and explains every answer. Here is the flow: one record in, one
> validated row out."

### Scene 2: The input (20 s). Open `data\raw\product_truth_agent_dataset.xlsx`, qa sheet
> "This is the qa sheet: 412 products. Retailer descriptions like these are
> abbreviated and messy, and no web pages are given. NIMO has to find them."

### Scene 3: One product, end to end (70 s). Browser, `qa:0`, click **Run again (warm)**
Scroll down the card slowly while you speak:
> "Brilliant teeth whitening charcoal kit. First NIMO cleans the description.
> It searched the web and fetched eight candidate pages. Look at them: the
> word 'Brilliant' also brought back paint pages and a tutoring website.
> The matcher picked the Superdrug product page for this exact kit, with a
> calibrated confidence of 0.93, which means about 93 in 100 such picks are
> right. Then the module, with the labelled example it most resembles. Then
> the characteristics that apply to this module, coded by the model and
> checked against NIQ's allowed values. And at the bottom, the reasoning.
> Every sentence is built from a recorded field, and the tags underneath
> show where each one came from."

### Scene 4: Characteristics (40 s). `qa:28`, **Run again (warm)**, scroll to *characteristics*
> "Here the module has nine applicable characteristics, all coded: baby and
> child, tube, 100 percent natural, milk teeth, without fluoride, aloe vera and
> mandarin. Only characteristics that apply to this module are ever filled.
> The rest stay empty, as the guidelines require."

### Scene 5: Memory (30 s). **TRY ANY PRODUCT**: the Pärla record from rehearsal step 4, **Resolve**
> "Now a product typed in with a different description but a barcode NIMO
> has seen before. It comes back instantly as tier-zero: answered from
> NIMO's memory of resolved products, with no web search at all. On a
> re-run of the qa set, 111 rows were answered this way."

Point at the **REGISTRY — THE MEMORY** table on the right.

### Scene 6: A brand-new product (40 s, optional). The Listerine record, **Resolve**
> "And a product NIMO has never seen. It searches live through the Brave
> Search API, ranks the candidates and explains its choice."

Pause the recording while it works, and resume when the card appears.

### Scene 7: The output file (40 s). Open `data\out\final\submission_qa.xlsx` in Excel
> "NIMO writes the submission file itself: 412 rows in the exact qa format,
> with the product URL, the reasoning, the module and the thirteen
> characteristic columns."

Scroll right slowly across the columns. Then open `data\out\final\site_qa.html`:
> "And every row can be checked in this results page. Search, filter by
> barcode-confirmed rows, open any card."

Set the *identity* filter to **GTIN-confirmed** and click one row.

### Scene 8: Close (20 s). Deck slide 6, then slide 7
> "All 412 products resolved, 114 confirmed by the page's own barcode, and
> reasoning you can check line by line. Thank you."

---

## 7. After recording

1. Trim the start, the end and any retakes (Clipchamp, or the Photos app → Edit → Trim).
2. Export as MP4 at 1080p. If the file is over 50 MB, export again at 720p.
3. Watch it once all the way through, with sound.
4. Name it `NIMO_Demo_MatrixSlayers.mp4`.

---

## If something goes wrong

| Symptom | Cause and fix |
|---|---|
| A card shows `http_error` on most fetch lines | The office network blocks retailer pages. Expected for new products; cached rows are unaffected |
| A dataset row fails with a search error | The cache is not unzipped in the right place (step 1.3) |
| `Brave API refused the key` / `no credit left` | Check `BRAVE_API_KEY` in `.env`; skip scene 6 |
| `Brave API call cap reached` | Safety cap of 150 paid calls per run. Something is not cached: check step 1.3 |
| The UI won't start: port in use | `uv run python -m nimo.ui --live --characteristics --port 8766`, then open http://127.0.0.1:8766 |
| The characteristics section says `gate_only` | The UI was started without `--characteristics`, or the model is unreachable (VPN) |
| A click seems to do nothing | Wait. A first model call takes 10–20 s. Rehearsal (section 4) avoids this |
