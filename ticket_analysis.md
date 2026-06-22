# Ticket Variation Analysis — Sheet 907937332547460

> Filter: SNAPP system + Received/Uncomplete status

## Summary

| Metric | Value |
|--------|-------|
| **Total tickets (filtered)** | 2,960 |
| **Unique variation types** | 47 |
| **Currently "Received" (pending)** | 239 |

---

## Service Type Breakdown

| Service | Count | % |
|---------|------:|--:|
| On-boarding (only) | 1,287 | 43.5% |
| Updating editor information | 814 | 27.5% |
| Off-boarding an editor | 724 | 24.5% |
| Recording editor unavailability | 93 | 3.1% |
| Inviting and on-boarding (editorial board) | 31 | 1.0% |
| Inviting and on-boarding an editor | 2 | 0.1% |

---

## Status Distribution

| Status | Count |
|--------|------:|
| Complete | 2,427 |
| Received (pending) | 239 |
| In progress - awaiting GPO | 135 |
| In progress | 49 |
| Rejected | 40 |
| Request incomplete | 35 |
| Action at a later date | 16 |
| Complete: candidates invited | 9 |

---

## The 47 Ticket Variations (Grouped by Action)

### ONBOARD (13 variations, ~1,320 tickets)

| # | Variation | Count | Example |
|---|-----------|------:|---------|
| 1 | ONBOARD + affiliation | 322 | Zafar Ali → Soft Computing |
| 2 | ONBOARD + affiliation + role | 204 | Gabriela Vasconcelos → Trials |
| 3 | ONBOARD + multiple editors | 132 | (bulk) → The Science of Nature |
| 4 | ONBOARD + collection + multiple editors | 85 | (bulk) → Climatic Change |
| 5 | ONBOARD + collection + affiliation | 77 | Quan Xu → Eur Physical Journal Plus |
| 6 | ONBOARD + affiliation + section | 75 | Karyn Allee → Early Childhood Education |
| 7 | ONBOARD + keywords + affiliation + role | 72 | David Okimait → J Epidemiology & Global Health |
| 8 | ONBOARD + collection + affiliation + role | 66 | Ricardo Moreno → Biological Research |
| 9 | ONBOARD + collection + role + multiple editors | 63 | (bulk) → J Happiness Studies |
| 10 | ONBOARD + role + multiple editors | 59 | (bulk) → Networks & Spatial Economics |
| 11 | ONBOARD + affiliation + role + section | 55 | Christophe Le Tourneau → Clinical Epigenetics |
| 12 | ONBOARD + keywords + affiliation | 35 | Hans-Christian Blum → Sleep and Breathing |
| 13 | ONBOARD + keywords + affiliation + role + section | 28 | Jin Peng He → J Medical Case Reports |
| 14 | ONBOARD + section + multiple editors | 23 | (bulk) → Intl J Ethics Education |
| 15 | ONBOARD + keywords + affiliation + section | 15 | Oguzhan Cetindemir → Innovative Infra Solutions |
| 16 | ONBOARD + role + section + multiple editors | 9 | (bulk) → J Thrombosis & Thrombolysis |

### OFFBOARD (4 variations, ~724 tickets)

| # | Variation | Count | Example |
|---|-----------|------:|---------|
| 1 | OFFBOARD (simple) | 538 | Andre Neves → Calculus of Variations |
| 2 | OFFBOARD + multiple editors | 138 | (bulk) → Brazilian J Microbiology |
| 3 | OFFBOARD + collection | 34 | Habib Hamam → J Geovisualization |
| 4 | OFFBOARD + collection + multiple editors | 14 | (bulk) → Biology & Fertility of Soils |

### UPDATE (23 variations, ~814 tickets)

| # | Variation | Count | Example |
|---|-----------|------:|---------|
| 1 | UPDATE + explain_update | 355 | "change city from Brisbane to Sydney" |
| 2 | UPDATE + explain_update + multiple editors | 114 | "change role from Member to Editor" |
| 3 | UPDATE + role + explain_update | 93 | "promoted to EiC starting Jan 2026" |
| 4 | UPDATE + section + explain_update | 70 | "become EiC, remove from Assoc Editor" |
| 5 | UPDATE (bare, no details) | 23 | Frank DelRio → Experimental Mechanics |
| 6 | UPDATE + collection + explain_update | 22 | "provide Guest Editor role ASAP" |
| 7 | UPDATE + role + explain_update + multiple editors | 20 | "two AEs will become EiCs in 2027" |
| 8 | UPDATE + section + explain_update + multiple editors | 18 | "remove Past Editors from webpage" |
| 9 | UPDATE + role | 14 | Daniel Vigo → Intl J Mental Health Systems |
| 10 | UPDATE + collection + role + explain_update | 13 | "correct guest editor's email" |
| 11 | UPDATE + role + section + explain_update | 12 | "taken off as AE, added as co-EIC" |
| 12 | UPDATE + multiple editors | 9 | (bulk) → J Korean Ceramic Society |
| 13 | UPDATE + keywords + role + explain_update | 8 | "promote to Assoc Editor, add keywords" |
| 14 | UPDATE + role + section + explain_update + multiple | 8 | "move four AEs to another section" |
| 15 | UPDATE + keywords + explain_update | 7 | "Please add keywords" |
| 16 | UPDATE + collection + explain_update + multiple | 6 | "add bios and photos of 5 guest editors" |
| 17 | UPDATE + section | 5 | Bryan Edwards → J Business & Psychology |
| 18 | UPDATE + collection + role + explain_update + multiple | 4 | "update misspellings of guest editor emails" |
| 19 | UPDATE + keywords + role + section + explain_update | 4 | "update topic and keywords in Snapp" |
| 20 | UPDATE + collection + section + explain_update | 2 | "change Prof. to Associate Professor" |
| 21 | UPDATE + keywords + section + explain_update | 2 | "change section and keywords, replace old" |
| 22 | UPDATE + collection | 2 | Lauren Haack → Research on Child Psychopathology |
| 23 | UPDATE + role + section | 1 | Christopher Barry → J Child & Family Studies |

### UNAVAILABILITY (1 variation, 93 tickets)

| # | Variation | Count | Example |
|---|-----------|------:|---------|
| 1 | UPDATE + unavail_dates | 93 | Carlos Chiesa Estomba → Eur Archives Oto-Rhino |

### OTHER (empty/unclassified)

| # | Variation | Count |
|---|-----------|------:|
| 1 | OTHER (no service field) | 9 |

---

## Key Observations

1. **ONBOARD + affiliation** is the single most common single-editor ticket (322). Your agent handles this well.
2. **UPDATE + explain_update** (355) is the largest update category — these rely heavily on free-text parsing.
3. **OFFBOARD (simple)** (538) is straightforward — just deactivate a single editor.
4. **~530 tickets involve "multiple editors"** — these are bulk tickets that require separate handling (currently skipped by the agent).
5. **93 unavailability tickets** — these are date-range based, relatively simple.
6. **9 empty/unclassified tickets** — rows with no service type, likely incomplete submissions.

> [!IMPORTANT]
> For the **variation showcase sheet** you want to create, I recommend picking **one real example ticket** from each of the top ~15-20 most common variations (covering all 4 action types). This gives full coverage of what the agent will encounter. Want me to proceed with building that sheet?
