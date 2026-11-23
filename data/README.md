# data/ (hanya dibaca oleh pipeline)

Isi dengan: `python3 tools/setup_data.py --zips /path/ke/02_DATASET`

Tata letak yang diharapkan:
```
data/scenario1/events/*.csv   (15 berkas)
data/scenario2/events/*.csv   (7 berkas)
data/scenario3/events/*.csv   (5 berkas)
data/tasks/event-summarization/ground-truth-single/*.json, ground-truth-multiple/*.json
data/tasks/keyword-analysis/ground-truth/*.json, additional-keywords.json
data/tasks/grep/ground-truth/*.txt
```
