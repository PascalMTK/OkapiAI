<div align="center">

<img src="frontend/assets/logo.jpg" alt="OkapiAI" width="230">

# OkapiAI

**Traduire, converser et apprendre les langues nationales de la RDC.**

Lingala · Swahili · Kikongo · Tshiluba

<p>
  <img src="https://img.shields.io/badge/Python-3.10%2B-1e7bff?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/FastAPI-backend-1e7bff?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/NLLB--200-traduction-f7d618?style=for-the-badge&logoColor=black" alt="NLLB-200">
  <img src="https://img.shields.io/badge/Claude-conversation-ce1021?style=for-the-badge" alt="Claude">
  <img src="https://img.shields.io/badge/statut-MVP-0a3fb8?style=for-the-badge" alt="Statut MVP">
</p>

[Fonctionnalités](#-fonctionnalités) ·
[Démarrage rapide](#-démarrage-rapide) ·
[Validation des données](#-validation-des-données) ·
[Configuration](#%EF%B8%8F-configuration) ·
[API](#-api) ·
[Entraînement](#-entraînement-des-modèles) ·
[Contribuer](#-contribuer)

</div>

---

## 🦓 À propos

Les langues congolaises sont parlées par des dizaines de millions de personnes, mais les outils numériques qui les comprennent restent rares. **OkapiAI** est une plateforme communautaire qui construit, avec les locuteurs eux-mêmes, des **données de qualité** (texte et voix). Ces données servent ensuite à entraîner des modèles de traduction, de reconnaissance vocale et de conversation.

Chaque phrase qui entre dans le dataset d'entraînement a été **proposée par au moins 10 personnes différentes**, puis **validée par un administrateur**.

<div align="center">
  <img src="docs/apercu.png" alt="Aperçu de l'interface OkapiAI" width="860">
</div>

## ✨ Fonctionnalités

| | Module | Description |
|---|---|---|
| 💬 | **Chat** | **Converser** : l'utilisateur écrit en langue nationale, le système **répond dans la même langue** (traduction française disponible). **Traduire** : un mot ou une phrase, dans les deux sens. |
| 🎙️ | **Voix live** | Les mêmes modes à la voix : on parle, la voix est transcrite, puis le système répond ou traduit. On peut enregistrer sa voix dans le dataset. |
| ➕ | **Contribuer** | Proposer une **traduction** ou un **dialogue** (message → réponse), avec la voix, et confirmer les propositions des autres. |
| 📚 | **Apprendre** | Cartes et quiz générés **uniquement** à partir des données validées, avec la prononciation enregistrée. |
| 🛡️ | **Administration** | Valider ou rejeter les propositions, corriger le texte final, écouter les voix, suivre les statistiques, exporter le dataset. |

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

### Modules optionnels

```bash
pip install torch transformers huggingface_hub imageio-ffmpeg   # voix live (MMS)
```

#### Conversation IA gratuite : Gemini + Groq

Copiez `backend/.env.example` en `backend/.env` et collez vos clés gratuites :
[Gemini](https://aistudio.google.com/apikey) (`GEMINI_API_KEY`) et [Groq](https://console.groq.com/keys) (`GROQ_API_KEY`).
OkapiAI essaie **Gemini, puis Groq** : si l'un atteint sa limite gratuite ou ne répond pas, l'autre prend le relais automatiquement. Aucun paquet à installer. Les IA restent ancrées sur le dataset validé et le dictionnaire, mais peuvent faire des erreurs en langue nationale : les utilisateurs peuvent corriger chaque réponse.

#### Voix live : parler avec OkapiAI

La voix live utilise les modèles **Meta MMS** : on parle, OkapiAI transcrit, répond dans la même langue **à voix haute**, puis réécoute (mode « Conversation continue »). En « Détection automatique », il reconnaît seul la langue parlée.

| Langue | Reconnaissance vocale | Voix d'OkapiAI |
|---|---|---|
| Lingala | ✅ `facebook/mms-1b-all` (adaptateur `lin`) | ✅ `khof312/mms-tts-lin` |
| Swahili | ✅ `facebook/mms-1b-all` (adaptateur `swh`) | ✅ `facebook/mms-tts-swh` |
| Tshiluba | ✅ `abdouaziiz/tshiluba` (Whisper small affiné, ~15 % de mots faux, Apache-2.0) → `backend/models/whisper-tshiluba/` | ⚠️ provisoire : la voix lingala lit le tshiluba |
| Kikongo | ⏳ pas encore de modèle public : on tape ce qu'on a dit | ⏳ pas encore |

Téléchargement unique des modèles (~4,3 Go, GPU conseillé mais pas obligatoire) :

```bash
python -c "from huggingface_hub import snapshot_download as d; d('khof312/mms-tts-lin'); d('facebook/mms-tts-swh'); d('facebook/mms-1b-all', allow_patterns=['*.json','model.safetensors','adapter.lin.safetensors','adapter.swh.safetensors','adapter.fra.safetensors'])"
# tshiluba (~1 Go)
python -c "from huggingface_hub import snapshot_download as d; d('abdouaziiz/tshiluba', local_dir='backend/models/whisper-tshiluba', allow_patterns=['*.json','*.txt','model.safetensors'])"
```

Tshiluba : en « Détection automatique », seuls le lingala et le swahili sont reconnus ; choisissez « Tshiluba » dans le menu Langue. Les phrases tshiluba (`dataset/sources/tshiluba/phrases.jsonl`, 23 791 phrases, corpus [DanMM96/Tshiluba-dataset](https://huggingface.co/datasets/DanMM96/Tshiluba-dataset), CC BY 4.0, surtout biblique) servent d'exemples à l'IA et de vocabulaire à l'écoute tolérante ; elles se régénèrent avec `python tools/import_tshiluba.py`.

Les modèles sont chargés au démarrage du serveur (en arrière-plan). Variables utiles : `OKAPI_ASR=off`, `OKAPI_TTS=off`, `OKAPI_VOICE_WARMUP=0`. Les voix MMS sont sous licence **CC BY-NC 4.0** (usage non commercial).

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

## 🗣️ Converser en langue nationale

```mermaid
flowchart LR
    Q[Message en lingala, swahili, kikongo ou tshiluba] --> D{Dialogue validé ?}
    D -->|oui| R1[Réponse de la communauté]
    D -->|non| I{IA activée ?}
    I -->|oui| R2["Réponse IA ancrée sur le dataset"]
    I -->|non| R3[« Apprenez-moi une réponse »]
    R1 & R2 & R3 --> F[✏️ Corriger → nouvelle contribution]
```

Le bot répond toujours **dans la langue de l'utilisateur**. Avec chaque message, l'IA reçoit les exemples validés les plus proches et est invitée à reprendre leur vocabulaire. Chaque réponse peut être **corrigée** : la correction suit le même circuit de validation, et le système s'améliore avec l'usage.

> [!NOTE]
> La qualité de l'IA est bonne en swahili, correcte en lingala, et plus faible en kikongo et en tshiluba. Les réponses générées sont signalées comme telles dans l'interface.

## ⚙️ Configuration

Toutes les options se règlent par variables d'environnement.

| Variable | Défaut | Rôle |
|---|---|---|
| `OKAPI_MIN_SIMILAR` | `10` | Nombre de contributeurs différents requis avant la revue admin |
| `OKAPI_SIMILARITY_THRESHOLD` | `0.85` | Seuil de similarité pour regrouper deux contributions |
| `OKAPI_LOOKUP_THRESHOLD` | `0.80` | Seuil pour qu'une recherche dans le dataset soit acceptée |
| `OKAPI_DATABASE_URL` | SQLite local | Ex. `postgresql+psycopg://user:pass@host/okapi` |
| `OKAPI_SECRET_KEY` | *(à changer)* | Clé de signature des sessions |
| `OKAPI_ADMIN_USERNAME` / `OKAPI_ADMIN_PASSWORD` | `admin` / `admin123` | Compte admin initial |
| `ANTHROPIC_API_KEY` | — | Active la conversation IA |
| `OKAPI_LLM_MODEL` | `claude-opus-5-5` | Modèle utilisé pour la conversation |
| `OKAPI_LLM_EFFORT` | `low` | Profondeur de réflexion (`low` → `max`) |
| `OKAPI_LLM_ENABLED` | — | `0` pour couper l'IA |
| `OKAPI_WHISPER_MODEL` | `small` | Taille du modèle de reconnaissance vocale |

> [!WARNING]
> Lorsque l'IA est activée, les messages des utilisateurs sont envoyés à l'API d'Anthropic, et chaque requête est facturée sur votre compte. Informez-en vos utilisateurs.

## 🔌 API

<details>
<summary><b>Voir les principaux points d'accès</b></summary>

| Méthode | Route | Description |
|---|---|---|
| `POST` | `/api/auth/register` · `/api/auth/login` | Créer un compte, se connecter |
| `POST` | `/api/converse` | Converser en langue nationale |
| `POST` | `/api/voice/converse` | Converser à la voix |
| `POST` | `/api/translate` · `/api/chat` | Traduire (réponse brute ou formulée) |
| `POST` | `/api/voice/chat` | Traduire à la voix |
| `POST` | `/api/contributions/text` · `/api/contributions/voice` | Proposer une traduction ou un dialogue |
| `GET` | `/api/contributions/proposals` | Propositions à confirmer |
| `POST` | `/api/contributions/proposals/{id}/confirm` | Confirmer une proposition |
| `GET` | `/api/learn/cards` · `/api/learn/quiz` | Cartes et quiz |
| `GET` | `/api/admin/propositions` | Propositions en attente *(admin)* |
| `POST` | `/api/admin/propositions/{id}/approve` · `/reject` | Décision admin *(admin)* |
| `GET` | `/api/admin/export/entrainement.jsonl` | Export du dataset d'entraînement *(admin)* |

La documentation complète et testable est générée automatiquement sur `/docs`.

</details>

## 🧠 Entraînement des modèles

OkapiAI s'appuie sur **NLLB-200** (Meta), qui connaît déjà les quatre langues, et l'affine avec le dataset validé par la communauté.

```bash
cd backend
pip install -r training/requirements.txt            # GPU recommandé

python -m training.export_dataset --out training/export
python -m training.train_nllb --data training/export/traduction.jsonl --epochs 5
```

| Fichier exporté | Usage |
|---|---|
| `traduction.jsonl` | Paires de traduction dans les deux sens → fine-tuning NLLB-200 |
| `dialogue.jsonl` | Paires message → réponse → chatbot conversationnel |
| `voix.jsonl` | Audio + transcription + langue → reconnaissance vocale (Whisper, MMS) |

Le modèle est enregistré dans `backend/models/okapi-nllb` et utilisé automatiquement au redémarrage. L'ordre de traduction est le suivant : **dataset validé → modèle entraîné → mot à mot**.

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
│   │       ├── llm.py           # Conversation IA (Claude), optionnelle
│   │       ├── translator.py    # Dataset → modèle NLLB → mot à mot
│   │       └── speech.py        # Reconnaissance vocale (faster-whisper), optionnelle
│   ├── training/                # Export du dataset et fine-tuning
│   └── tests/
├── frontend/                    # Interface web (HTML · Tailwind · JavaScript)
├── app/                         # Recherche et dictée sur le corpus lingala (Node, port 8787)
├── dataset/                     # Corpus lingala (métadonnées versionnées, audio local)
│   ├── clips/<video_id>/        # Extraits de cours YouTube + metadata.jsonl (à relire)
│   ├── knowledge/               # Lexique, grammaire et sections Wikipédia
│   ├── sources/                 # LRSC (parole lue, CC BY 4.0) · Peace Corps · Kaikki
│   └── raw/                     # Téléchargements bruts (non versionnés, sauf wikipedia/)
├── tools/                       # Scripts de collecte, d'import et de relecture du corpus
└── docs/
```

### Corpus lingala (`dataset/` et `tools/`)

| Commande | Rôle |
|---|---|
| `python tools/cut_videos.py <lien YouTube>` | Télécharge une vidéo ou un Short et la découpe en phrases |
| `python tools/import_lrsc.py` | Importe le Lingala Read Speech Corpus (Hugging Face) |
| `python tools/import_peace_corps.py` · `import_wikipedia.py` · `import_maloba.py` | Importent les sources texte |
| `python tools/tag_language.py` · `transcribe_ln.py` | Repèrent et transcrivent les passages en lingala des clips |
| `python tools/review_server.py` | Interface de relecture des clips (http://localhost:8765) |

L'application de recherche se lance avec `node app/server.mjs` (Node 20+), puis http://127.0.0.1:8787.

**Stack :** FastAPI · SQLAlchemy 2 · SQLite / PostgreSQL · Tailwind CSS · Lucide · JavaScript · Hugging Face Transformers · Anthropic SDK · faster-whisper

## 🧪 Tests

```bash
cd backend
python tests/test_flow.py
```

Les tests couvrent le circuit complet : seuil des 10 contributeurs, anti-spam, validation admin, traduction dans les deux sens, contributions vocales, droits d'accès aux audios et conversation. L'IA y est simulée, donc aucun appel réseau n'est fait.

## 🗺️ Feuille de route

- [x] Traduction communautaire validée (10 contributeurs + admin)
- [x] Collecte vocale et apprentissage
- [x] Conversation en langue nationale
- [ ] Synthèse vocale entraînée sur les voix validées, pour que le bot parle lingala ou tshiluba
- [x] Reconnaissance vocale du tshiluba
- [ ] Reconnaissance vocale du kikongo, voix tshiluba entraînée
- [ ] Conversation vocale en streaming (WebSocket)
- [ ] Limitation de débit et nettoyage automatique des audios non utilisés
- [ ] Application mobile

## 🤝 Contribuer

OkapiAI a d'abord besoin de **locuteurs natifs**. La meilleure façon de contribuer est d'utiliser la plateforme : proposer des phrases, enregistrer sa voix et confirmer les propositions des autres.

Pour contribuer au code :

1. Créez une branche : `git checkout -b ma-fonctionnalite`
2. Vérifiez que les tests passent : `python tests/test_flow.py`
3. Ouvrez une *pull request* qui décrit le changement

> [!CAUTION]
> Ne commitez jamais les données de la plateforme (`backend/data/`, exports `*.jsonl`), les fichiers audio ni les modèles entraînés : ils sont exclus par le `.gitignore`. Seules les métadonnées de `dataset/` sont versionnées.

## 📄 Licence

La licence du projet n'a pas encore été choisie. Tant qu'aucune licence n'est publiée, tous les droits sont réservés aux auteurs.

---

<div align="center">

**Fait avec ❤️ pour les langues de la République démocratique du Congo** 🇨🇩

</div>
