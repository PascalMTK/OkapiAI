# 🦒 OkapiAI

Plateforme communautaire pour **traduire, parler et apprendre** les langues congolaises :
**lingala, swahili, kikongo, tshiluba** (avec le français comme langue pivot).

## Fonctionnalités

| Onglet | Rôle |
|---|---|
| 💬 **Chat** | Mode **Converser** : on écrit en lingala, swahili, kikongo ou tshiluba, le système **répond dans la même langue** (avec la traduction française). Mode **Traduire** : traduction d'un mot ou d'une phrase. |
| 🎙️ **Voix live** | Les deux mêmes modes, à la voix : on parle → transcription (si disponible) → réponse ou traduction. |
| ➕ **Contribuer** | Ajouter une traduction ou un **dialogue** (message → réponse), avec la voix, et confirmer les propositions des autres. |
| 📚 **Apprendre** | Cartes et quiz générés **uniquement** à partir des données validées, avec les voix. |
| 🛡️ **Admin** | Valider ou rejeter les propositions, statistiques, export du dataset. |

## Les deux datasets

```
 Utilisateurs ──► dataset_collecte (brut, texte + voix)
                       │  regroupement par similarité (≥ 85 %)
                       ▼
                  propositions ── moins de 10 personnes ─► statut "collecte"
                       │  ≥ 10 personnes DIFFÉRENTES
                       ▼
                  "en_attente_admin" ── admin rejette ─► "rejete"
                       │  admin approuve
                       ▼
                 dataset_entrainement (validé) ──► traduction, apprentissage, entraînement des modèles
```

- Une même personne ne compte qu'**une seule fois** par proposition (anti-spam).
- Les variantes proches (« Mbote na yo », « mbote na yo! », « Mbote na yoo ») sont comptées ensemble.
- L'admin peut corriger le texte final avant d'approuver. Il **ne peut pas** approuver avant d'atteindre le seuil.
- Les voix brutes sont privées (visibles par leur auteur et l'admin). Elles deviennent publiques une fois validées.

Paramètres (variables d'environnement) : `OKAPI_MIN_SIMILAR` (10 par défaut), `OKAPI_SIMILARITY_THRESHOLD` (0.85).

## Converser en langue nationale

Le bot répond, dans l'ordre :
1. avec un **dialogue validé** par la communauté (10 personnes, puis l'admin) ;
2. sinon avec **l'IA (Claude)**, si elle est activée. Avec chaque message, elle reçoit les exemples validés les plus proches, et elle est invitée à reprendre leur vocabulaire ;
3. sinon, il demande à l'utilisateur de lui **apprendre une réponse**.

Chaque réponse a un bouton **✏️ Corriger**. La correction devient une contribution « dialogue », soumise à la même règle des 10 personnes et de l'admin. Les réponses de l'IA améliorent ainsi le dataset au fil du temps.

Pour activer l'IA :

```bash
pip install anthropic
set ANTHROPIC_API_KEY=sk-ant-...      # Linux/Mac : export ANTHROPIC_API_KEY=...
```

Les options sont `OKAPI_LLM_MODEL` (par défaut `claude-opus-5-5`), `OKAPI_LLM_EFFORT` (par défaut `low`) et `OKAPI_LLM_ENABLED=0` pour la couper.
⚠️ Chaque message envoyé à l'IA est facturé sur votre compte Anthropic. Les messages des utilisateurs sont envoyés à l'API d'Anthropic : prévenez-les.
La qualité est bonne en swahili, correcte en lingala, et plus faible en kikongo et en tshiluba. Ce sont justement les corrections de la communauté qui comblent ces écarts.

## Démarrage

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows   (Linux/Mac : source .venv/bin/activate)
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Ouvrir http://localhost:8000. Le compte admin par défaut est `admin` / `admin123`.
**Changez-le** avec `OKAPI_ADMIN_USERNAME`, `OKAPI_ADMIN_PASSWORD` et `OKAPI_SECRET_KEY` avant toute mise en ligne.

Documentation de l'API : http://localhost:8000/docs

### Reconnaissance vocale (optionnelle)

```bash
pip install faster-whisper
```

Whisper reconnaît le **swahili, le lingala et le français**. Pour le **kikongo et le tshiluba**,
l'utilisateur tape ce qu'il a dit. Ces enregistrements servent à entraîner plus tard un modèle vocal dédié.

## Entraîner le modèle de traduction

Le système utilise **NLLB-200** (Meta), qui connaît déjà les 4 langues. On l'affine avec le dataset validé :

```bash
cd backend
pip install -r training/requirements.txt
python -m training.export_dataset --out training/export     # traduction.jsonl + dialogue.jsonl + voix.jsonl
python -m training.train_nllb --data training/export/traduction.jsonl --epochs 5
```

Le modèle est enregistré dans `backend/models/okapi-nllb`. L'API l'utilise automatiquement au redémarrage.
Ordre de traduction : **dataset validé → modèle entraîné → mot à mot**.

`voix.jsonl` (audio + texte + langue) est prêt pour l'entraînement d'un modèle de reconnaissance vocale
(ex. fine-tuning Whisper ou MMS).

## Tests

```bash
cd backend
python tests/test_flow.py
```

## Structure

```
backend/
  app/
    main.py            # application FastAPI + service des audios
    models.py          # tables : users, propositions, dataset_collecte, dataset_entrainement
    services/dataset.py    # règle des 10 similaires + validation admin
    services/translator.py # dataset -> modèle -> mot à mot
    services/speech.py     # reconnaissance vocale (faster-whisper)
    routers/           # auth, chat/voix, contributions, learn, admin
  training/            # export du dataset + fine-tuning NLLB
  tests/
frontend/              # interface web (HTML/CSS/JS)
```

## Prochaines étapes conseillées

- PostgreSQL en production (`OKAPI_DATABASE_URL=postgresql+psycopg://...`).
- Limite de requêtes et nettoyage des audios de « Voix live » jamais ajoutés au dataset.
- Synthèse vocale (TTS) entraînée sur les voix validées, pour faire parler le chatbot en lingala ou en tshiluba.
- Chat vocal en streaming (WebSocket) au lieu du mode « appuyer pour parler ».
