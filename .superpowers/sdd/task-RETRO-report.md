# RETRO — curățare retroactivă aplicată pe live (2026-10-26, ~21:38 UTC)

- Git: fix/retro-merge rebazat peste origin/feat/app (5c921d3) -> 54f341f; script offline, VERSION neschimbat (Beta 1.24); 1334 teste trec. Regula de gemeni din 1.24 (quality: near_dup/minority_dup) nu se suprapune: scriptul ignoră fantomele.
- Dry-run live (mode=ro): identic cu raportul Q122data: 29 comasări (toate relația "noise", 0 cadre comune) + 2 aliasuri (KIEV -CHISINAU 4 servicii/61 obs; VATRA DORNEI BA 1/186). Listate necomasate: 5011/5014, 11081/41081, 10055/55, 8093/93, 5019/19; ore divergente 16593, 1658, 10101, 10261.
- Backup: /root/tabela-retro-20261026T213622Z/ (pre.db, integrity ok; tabela-before-merge-20261026-213757.db luat de --apply; apply.json, quality.json).
- Batch restaurare: MD20261026T213800Z (`python scripts/merge_number_dups.py --db /var/lib/tabela/tabela.db --restore --batch MD20261026T213800Z`, cu serviciul oprit; script la /root/retro-run/scripts/).
- Apply: serviciu oprit (~1 min), 29 servicii comasate, 254 observații mutate, 17 rânduri de catalog retrase, `app.quality` rulat, apoi marcaje: last_delay=15 pe 629/641/676/855, event_quality 'arrow_glyph' pe 3648/3667/3684/3687/3824/3832/4510. Repetat întâi pe o copie. Atenție: `python -m app.quality` rulat din nou poate reseta ("cleared") marcajele arrow_glyph, deoarece sunt derivate; de reaplicat marks.sql după.
- Înainte -> după: servicii 2375 -> 2346; /api/stats/overview călătorii 2124 -> 2087, trenuri distincte 421 -> 393; /api/history?all=1 total 2292 -> 2254; excluse ghost 83 -> 92.
- Verificări live: health ok, 12/12 rânduri pe ambele panouri în 3 cicluri, KIEV - CHISINAU o singură stație, VATRA DORNEI BAI, fără avertismente în jurnal.
