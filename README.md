<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/logo-readme-dark.png">
  <img src="docs/logo-readme.png" alt="OkapiAI" width="220">
</picture>

# OkapiAI

### Parler, traduire et apprendre les langues nationales de la RDC

**Lingala** · **Swahili** · **Tshiluba** · **Kikongo**

<p>
  <img src="https://img.shields.io/badge/Python-3.10%2B-1e7bff?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/FastAPI-backend-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/IA-Gemini%20%E2%86%92%20Groq-f7d618?style=flat-square" alt="Gemini puis Groq">
  <img src="https://img.shields.io/badge/voix-MMS%20%C2%B7%20Whisper%20%C2%B7%20VITS-ce1021?style=flat-square" alt="MMS, Whisper, VITS">
  <img src="https://img.shields.io/badge/statut-MVP-0a3fb8?style=flat-square" alt="Statut MVP">
</p>

<sub>

[À propos](#-à-propos) ·
[Fonctionnalités](#-fonctionnalités) ·
[Langues](#-état-des-langues) ·
[Démarrage](#-démarrage-rapide) ·
[Voix](#%EF%B8%8F-voix-live) ·
[Données](#-validation-des-données) ·
[Configuration](#%EF%B8%8F-configuration) ·
[Entraînement](#-entraînement-des-modèles) ·
[Contribuer](#-contribuer)

</sub>

</div>

<br>

## 🦓 À propos

Les langues congolaises sont parlées par des dizaines de millions de personnes, mais les outils numériques qui les comprennent restent rares. **OkapiAI** est une plateforme communautaire qui construit, avec les locuteurs eux-mêmes, des **données de qualité** (texte et voix). Ces données servent ensuite à entraîner des modèles de traduction, de reconnaissance vocale, de synthèse vocale et de conversation.

> [!TIP]
> Chaque phrase qui entre dans le dataset d'entraînement a été **proposée par au moins 10 personnes différentes**, puis **validée par un administrateur**.

<div align="center">
  <img src="docs/apercu.png" alt="Aperçu de l'interface OkapiAI" width="860">
</div>

## ✨ Fonctionnalités

<table>
  <tr>
    <td width="50%" valign="top">
      <h3>💬 Chat</h3>
      <b>Converser</b> : on écrit en langue nationale, OkapiAI <b>répond dans la même langue</b> (traduction française à côté).<br>
      <b>Traduire</b> : un mot ou une phrase, dans les deux sens.
    </td>
    <td width="50%" valign="top">
      <h3>🎙️ Voix live</h3>
      On parle, OkapiAI transcrit, répond <b>à voix haute</b> puis réécoute. On peut lui couper la parole à tout moment. L'<b>écoute tolérante</b> comprend un apprenant qui prononce mal.
    </td>
  </tr>
  <tr>
    <td valign="top">
      <h3>➕ Contribuer</h3>
      Proposer une <b>traduction</b> ou un <b>dialogue</b> (message → réponse), avec sa voix, et confirmer les propositions des autres.
    </td>
    <td valign="top">
      <h3>📚 Apprendre</h3>
      Cartes et quiz générés <b>uniquement</b> à partir des données validées, avec la prononciation enregistrée.
    </td>
  </tr>
  <tr>
    <td colspan="2" valign="top">
      <h3>🛡️ Administration</h3>
      Valider ou rejeter les propositions, corriger le texte final, écouter les voix, suivre les statistiques, exporter le dataset.
    </td>
  </tr>
</table>

## 🌍 État des langues

| Langue | Conversation | Reconnaissance vocale | Voix d'OkapiAI |
|---|:---:|---|---|
| 🟦 **Lingala** | ✅ correcte | ✅ `facebook/mms-1b-all` (adaptateur `lin`) | ✅ VITS Open Bible lingala (secours : `khof312/mms-tts-lin`) |
| 🟩 **Swahili** | ✅ bonne | ✅ `facebook/mms-1b-all` (adaptateur `swh`) | ✅ `facebook/mms-tts-swh` |
| 🟨 **Tshiluba** | 🟡 plus faible | ✅ `abdouaziiz/tshiluba` (Whisper small affiné) | 🔄 voix tshiluba en cours d'entraînement (provisoire : la voix lingala) |
| 🟥 **Kikongo** | 🟡 plus faible | ⏳ pas encore de modèle public : on tape ce qu'on a dit | ⏳ pas encore |

> [!NOTE]
> Les réponses générées par l'IA sont signalées comme telles dans l'interface. Chaque réponse peut être **corrigée**, et la correction suit le circuit de validation.

## 🚀 Démarrage rapide

**Prérequis :** Python 3.10 ou plus récent.

```bash
git clone https://github.com/PascalMTK/OkapiAI.git
cd OkapiAI/backend

python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # Linux / macOS

pip install -r requirements.txt
uvicorn app.main:app --reload
```

| Adresse | Page |
|---|---|
| **http://localhost:8000** | Application (chat, voix, contributions, apprentissage) |
| **http://localhost:8000/admin** | Panneau d'administration |
| **http://localhost:8000/docs** | Documentation interactive de l'API |

> [!IMPORTANT]
> Un compte administrateur `admin` / `admin123` est créé au premier démarrage.
> Changez `OKAPI_ADMIN_PASSWORD` et `OKAPI_SECRET_KEY` avant toute mise en ligne.

### 🤖 Conversation IA gratuite : Gemini + Groq

Copiez `backend/.env.example` en `backend/.env` et collez vos clés gratuites :
[Gemini](https://aistudio.google.com/apikey) (`GEMINI_API_KEY`) et [Groq](https://console.groq.com/keys) (`GROQ_API_KEY`).

OkapiAI essaie **Gemini, puis Groq** : si l'un atteint sa limite gratuite ou ne répond pas, l'autre prend le relais automatiquement. Aucun paquet à installer. Les IA restent ancrées sur le dataset validé, le lexique et le corpus, mais peuvent faire des erreurs en langue nationale.

## 🎙️ Voix live

```bash
pip install torch transformers huggingface_hub imageio-ffmpeg
```

Téléchargement unique des modèles (~5 Go, GPU conseillé mais pas obligatoire) :

```bash
# lingala et swahili (MMS)
python -c "from huggingface_hub import snapshot_download as d; d('khof312/mms-tts-lin'); d('facebook/mms-tts-swh'); d('facebook/mms-1b-all', local_dir='backend/models/mms-1b-all', allow_patterns=['*.json','model.safetensors','adapter.lin.safetensors','adapter.swh.safetensors','adapter.fra.safetensors'])"
# tshiluba (~1 Go)
python -c "from huggingface_hub import snapshot_download as d; d('abdouaziiz/tshiluba', local_dir='backend/models/whisper-tshiluba', allow_patterns=['*.json','*.txt','model.safetensors'])"
```

En « Détection automatique », OkapiAI reconnaît seul le lingala et le swahili ; pour le tshiluba, choisissez « Tshiluba » dans le menu Langue.

### Voix plus naturelles (VITS)

Les voix entraînées tournent dans un petit serveur séparé, lancé avec le Python où `coqui-tts` est installé :

```bash
python tools/voice_server.py --port 8100                         # lingala
python tools/voice_server.py --speaker tshiluba --port 8101      # tshiluba
```

Puis, dans `backend/.env` : `OKAPI_TTS_LN_URL=http://127.0.0.1:8100` et `OKAPI_TTS_LUA_URL=http://127.0.0.1:8101`. Si un serveur ne répond pas, OkapiAI repasse automatiquement sur la voix MMS.

> [!WARNING]
> Les voix MMS sont sous licence **CC BY-NC 4.0** (usage non commercial). La voix Open Bible lingala est sous **CC BY-SA 4.0**.

## 🧭 Validation des données

OkapiAI sépare strictement **deux datasets** :

| Dataset | Table | Contenu |
|---|---|---|
| **Collecte** | `dataset_collecte` | Tout ce que les utilisateurs envoient, texte et voix, sans filtre. |
| **Entraînement** | `dataset_entrainement` | Uniquement les données qui ont atteint le seuil communautaire **et** ont été approuvées par un admin. |

```mermaid
flowchart LR
    U([Utilisateurs]) -->|texte + voix| C[(Dataset de collecte)]
    C -->|regroupement par similarité ≥ 85 %| P{Proposition}
    P -->|moins de 10 personnes| W[En collecte]
    W -.->|d'autres confirment| P
    P -->|10 personnes différentes ou plus| A{Admin}
    A -->|rejette| R[Rejetée]
    A -->|approuve| T[(Dataset d'entraînement)]
    T --> M1[Traduction]
    T --> M2[Conversation]
    T --> M3[Apprentissage]
    T --> M4[Entraînement des modèles]
```

- **Anti-spam :** une même personne ne compte qu'une seule fois par proposition.
- **Variantes :** « Mbote na yo », « mbote na yo! » et « Mbote na yoo » sont comptées ensemble.
- **Pas de raccourci :** l'admin peut corriger le texte final, mais **ne peut pas** approuver avant le seuil.
- **Voix privées :** les enregistrements bruts ne sont visibles que par leur auteur et l'admin. Ils deviennent publics une fois validés.

### Comment OkapiAI répond

```mermaid
flowchart LR
    Q[Message en langue nationale] --> D{Dialogue validé ?}
    D -->|oui| R1[Réponse de la communauté]
    D -->|non| I{IA disponible ?}
    I -->|oui| R2["Gemini → Groq, ancrés sur le dataset"]
    I -->|non| R3[« Apprenez-moi une réponse »]
    R1 & R2 & R3 --> F[✏️ Corriger → nouvelle contribution]
```

## ⚙️ Configuration

Toutes les options se règlent par variables d'environnement (ou dans `backend/.env`).

<details>
<summary><b>Plateforme et données</b></summary>

| Variable | Défaut | Rôle |
|---|---|---|
| `OKAPI_MIN_SIMILAR` | `10` | Contributeurs différents requis avant la revue admin |
| `OKAPI_SIMILARITY_THRESHOLD` | `0.85` | Seuil de similarité pour regrouper deux contributions |
| `OKAPI_LOOKUP_THRESHOLD` | `0.80` | Seuil pour qu'une recherche dans le dataset soit acceptée |
| `OKAPI_DATABASE_URL` | SQLite local | Ex. `postgresql+psycopg://user:pass@host/okapi` |
| `OKAPI_SECRET_KEY` | *(à changer)* | Clé de signature des sessions |
| `OKAPI_ADMIN_USERNAME` / `OKAPI_ADMIN_PASSWORD` | `admin` / `admin123` | Compte admin initial |

</details>

<details>
<summary><b>Conversation IA</b></summary>

| Variable | Défaut | Rôle |
|---|---|---|
| `GEMINI_API_KEY` · `GROQ_API_KEY` | — | Clés gratuites des services IA |
| `OKAPI_LLM_PROVIDERS` | `gemini,groq` | Ordre d'essai des services |
| `OKAPI_GEMINI_MODEL` | `gemini-flash-lite-latest` | Modèle Gemini |
| `OKAPI_GROQ_MODEL` | `openai/gpt-oss-120b` | Modèle Groq |
| `OKAPI_LLM_TIMEOUT` | `12` | Délai maximum d'une réponse (secondes) |
| `OKAPI_LLM_ENABLED` | — | `0` pour couper l'IA |

</details>

<details>
<summary><b>Voix</b></summary>

| Variable | Défaut | Rôle |
|---|---|---|
| `OKAPI_ASR` | `mms` | Reconnaissance vocale : `mms`, `whisper` ou `off` |
| `OKAPI_ASR_DEVICE` · `OKAPI_TTS_DEVICE` | auto | `cpu` pour laisser la carte graphique libre |
| `OKAPI_TTS` | `on` | `off` pour couper la voix d'OkapiAI |
| `OKAPI_TTS_LN_URL` · `OKAPI_TTS_LUA_URL` | — | Serveurs de voix VITS (lingala, tshiluba) |
| `OKAPI_VOICE_WARMUP` | — | `0` pour ne pas charger les modèles au démarrage |

</details>

> [!WARNING]
> Lorsque l'IA est activée, les messages des utilisateurs sont envoyés à Google (Gemini) ou à Groq. Informez-en vos utilisateurs.

## 🧠 Entraînement des modèles

### Traduction (NLLB-200)

OkapiAI s'appuie sur **NLLB-200** (Meta), qui connaît déjà les quatre langues, et l'affine avec le dataset validé.

```bash
cd backend
pip install -r training/requirements.txt            # GPU recommandé
python -m training.export_dataset --out training/export
python -m training.train_nllb --data training/export/traduction.jsonl --epochs 5
```

| Fichier exporté | Usage |
|---|---|
| `traduction.jsonl` | Paires de traduction dans les deux sens → NLLB-200 |
| `dialogue.jsonl` | Paires message → réponse → conversation |
| `voix.jsonl` | Audio + transcription + langue → reconnaissance vocale |

L'ordre de traduction est : **dataset validé → modèle entraîné → mot à mot**.

### Voix d'OkapiAI (VITS)

`tools/train_voice.py` affine la voix lingala Open Bible sur un seul lecteur, puis vérifie qu'elle se comprend avant de la mettre en service.

```mermaid
flowchart LR
    D[Enregistrements d'un lecteur] -->|prepare| P[Phrases 22 kHz + texte]
    P -->|train| C[Sauvegardes]
    C -->|check : écoutées par la reconnaissance vocale| V{Lettres mal comprises ≤ 12 % ?}
    V -->|oui| A[approved_model.pth → voice_server]
    V -->|non| B[La voix d'origine reste utilisée]
```

```bash
python tools/train_voice.py prepare --speaker tshiluba
python tools/train_voice.py train   --speaker tshiluba --fp16 --batch 4 --epochs 30
python tools/train_voice.py train   --speaker tshiluba --fp16 --resume              # reprendre
python tools/train_voice.py check   --speaker tshiluba                              # backend lancé
```

## 🏗️ Architecture

```
OkapiAI/
├── backend/
│   ├── app/
│   │   ├── main.py              # Application FastAPI, migrations, audios
│   │   ├── models.py            # users · propositions · dataset_collecte · dataset_entrainement
│   │   ├── routers/             # auth · chat & voix · contributions · learn · admin
│   │   └── services/
│   │       ├── dataset.py       # Règle des 10 contributeurs + validation admin
│   │       ├── conversation.py  # Dialogue validé → IA → « apprenez-moi »
│   │       ├── llm.py           # Relais Gemini → Groq
│   │       ├── translator.py    # Dataset → modèle NLLB → mot à mot
│   │       ├── speech.py        # Reconnaissance vocale (MMS, Whisper tshiluba)
│   │       ├── hearing.py       # Écoute tolérante (prononciation d'apprenant)
│   │       ├── tts.py           # Voix d'OkapiAI (serveur VITS ou MMS)
│   │       ├── lexicon.py · corpus.py · basics.py   # Dictionnaire, corpus, phrases de base
│   │       └── recordings.py    # Enregistrements du dataset sous les réponses
│   ├── training/                # Export du dataset et fine-tuning NLLB
│   └── tests/
├── frontend/                    # Interface web (HTML · Tailwind · JavaScript)
├── app/                         # Recherche et dictée sur le corpus lingala (Node, port 8787)
├── dataset/                     # Corpus (métadonnées versionnées, audio local)
│   ├── clips/<video_id>/        # Extraits de cours YouTube + metadata.jsonl
│   ├── knowledge/               # Lexique, grammaire et sections Wikipédia
│   ├── sources/                 # LRSC · Peace Corps · Kaikki · Tshiluba
│   └── raw/                     # Téléchargements bruts (non versionnés, sauf wikipedia/)
├── tools/                       # Collecte, import, relecture, voix
└── docs/
```

<details>
<summary><b>Outils du corpus (<code>tools/</code>)</b></summary>

| Commande | Rôle |
|---|---|
| `python tools/cut_videos.py <lien YouTube>` | Télécharge une vidéo ou un Short et la découpe en phrases |
| `python tools/import_lrsc.py` | Importe le Lingala Read Speech Corpus (CC BY 4.0) |
| `python tools/import_tshiluba.py` | Importe les phrases tshiluba ([DanMM96/Tshiluba-dataset](https://huggingface.co/datasets/DanMM96/Tshiluba-dataset), CC BY 4.0) |
| `python tools/import_peace_corps.py` · `import_wikipedia.py` · `import_maloba.py` | Importent les sources texte |
| `python tools/tag_language.py` · `transcribe_ln.py` | Repèrent et transcrivent les passages en lingala des clips |
| `python tools/review_server.py` | Interface de relecture des clips (http://localhost:8765) |
| `python tools/train_voice.py` · `voice_server.py` | Entraînent et servent les voix VITS |

L'application de recherche se lance avec `node app/server.mjs` (Node 20+), puis http://127.0.0.1:8787.

</details>

**Stack :** FastAPI · SQLAlchemy 2 · SQLite / PostgreSQL · Tailwind CSS · Lucide · JavaScript · Hugging Face Transformers · Meta MMS · Whisper · Coqui TTS (VITS) · Gemini · Groq

## 🧪 Tests

```bash
cd backend
python tests/test_flow.py
```

Les tests couvrent le circuit complet : seuil des 10 contributeurs, anti-spam, validation admin, traduction dans les deux sens, contributions vocales, droits d'accès aux audios et conversation. L'IA y est simulée, donc aucun appel réseau n'est fait.

## 🗺️ Feuille de route

- [x] Traduction communautaire validée (10 contributeurs + admin)
- [x] Collecte vocale et apprentissage
- [x] Conversation en langue nationale (Gemini → Groq)
- [x] Voix live avec barge-in et écoute tolérante
- [x] Reconnaissance vocale du lingala, du swahili et du tshiluba
- [x] Voix lingala claire (VITS Open Bible)
- [ ] Voix tshiluba entraînée *(en cours)*
- [ ] Voix lingala avec l'accent d'un locuteur du corpus
- [ ] Reconnaissance vocale et voix du kikongo
- [ ] Limitation de débit et nettoyage automatique des audios non utilisés
- [ ] Application mobile

## 🤝 Contribuer

OkapiAI a d'abord besoin de **locuteurs natifs**. La meilleure façon de contribuer est d'utiliser la plateforme : proposer des phrases, enregistrer sa voix et confirmer les propositions des autres.

Pour contribuer au code :

1. Créez une branche : `git checkout -b ma-fonctionnalite`
2. Vérifiez que les tests passent : `python tests/test_flow.py`
3. Ouvrez une *pull request* qui décrit le changement

> [!CAUTION]
> Ne commitez jamais `backend/.env` (vos clés), les données de la plateforme (`backend/data/`, exports `*.jsonl`), les fichiers audio ni les modèles entraînés : ils sont exclus par le `.gitignore`. Seules les métadonnées de `dataset/` sont versionnées.

## 📄 Licence

La licence du projet n'a pas encore été choisie. Tant qu'aucune licence n'est publiée, tous les droits sont réservés aux auteurs. Les modèles et corpus utilisés gardent leur propre licence (voir ci-dessus).

---

<div align="center">

<img src="frontend/assets/logo-mark.png" alt="" width="48">

**Fait avec ❤️ pour les langues de la République démocratique du Congo** 🇨🇩

</div>
