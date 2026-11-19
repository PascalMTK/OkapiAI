# OkapiAI

Depuis la racine du dépôt, lance `node app/server.mjs` avec Node.js 20 ou supérieur,
puis ouvre <http://127.0.0.1:8787>. Chrome et Edge permettent de tester la dictée
en français et en anglais selon les fonctions et autorisations disponibles dans
le navigateur. La dictée utilise le service de reconnaissance du navigateur.

Le mode par défaut recherche dans le lexique, les dialogues, les documents et
les transcriptions validées du corpus. Les résultats associés à un extrait
permettent d'écouter directement l'enregistrement. La lecture des réponses
utilise la voix française ou anglaise disponible dans le navigateur. Pour un
résultat en lingala, le lecteur privilégie l'enregistrement associé, puis une
voix lingala si le navigateur en propose une. Sinon, il adapte les syllabes,
les voyelles et la hauteur des tons marqués pour une voix francophone. Une
voix française du Congo est privilégiée si elle est disponible.

## Modèle conversationnel local

Avec Ollama lancé sur le port 11434, indique le nom exact de ton modèle local
dans PowerShell avant de démarrer le serveur.

```powershell
$env:OKAPI_MODEL = 'nom-du-modele'
node app/server.mjs
```

OkapiAI transmet au modèle les résultats pertinents du corpus et les derniers
messages. Si le modèle est indisponible, l'interface affiche les résultats de
recherche.

## PicoTTS

Si tu disposes d'un exécutable Windows compatible avec la commande
`pico2wave`, indique son chemin dans `OKAPI_PICO` avant de lancer le serveur.
PicoTTS propose des voix françaises et anglaises fixes. Les enregistrements
lingalaphones se lisent directement dans les résultats du corpus. Une voix
générée avec un accent lingalaphone nécessite un moteur vocal entraîné ou adapté.
