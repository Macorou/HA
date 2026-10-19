# Smart Heat Manager — 0.1.0

Intégration personnalisée Home Assistant pour réguler des pièces à partir de
sondes externes, coordonner une PAC existante et arbitrer Tempo EDF et surplus
photovoltaïque. Indépendante de Versatile Thermostat. Interface française et anglaise.

**Version initiale à réceptionner sur Home Assistant et sur l'installation réelle.**
Elle démarre en observation, calcule les décisions et expose les entités sans envoyer
de commandes. Le contrôleur physique est implémenté, avec un armement explicite par
session ; aucune compatibilité matérielle LG non vérifiée n'est annoncée.

## Installation locale

1. Extraire `dist/smart_heat_manager-0.1.0.zip` dans le dossier de configuration HA.
   Le chemin final doit être `config/custom_components/smart_heat_manager/manifest.json`.
2. Redémarrer Home Assistant (version minimale déclarée : 2025.12).
3. Ouvrir **Paramètres → Appareils et services → Ajouter une intégration → Smart Heat Manager**.
4. Choisir l'entité `climate` existante de la PAC, puis configurer au moins une pièce
   dans **Gestion des pièces** et enregistrer. Aucun identifiant n'est prédéfini.
5. Configurer les fonctions souhaitées depuis **Configurer** : présence, Tempo,
   photovoltaïque, surveillance et temporisations. Tout reste modifiable dans les options.

Les capteurs de puissance doivent publier des **W ou kW** instantanés, pas des kWh.
Les températures peuvent être en °C ou °F ; le moteur travaille en °C. Les actionneurs
doivent être des `climate`, des `number` en pourcentage 0–100 ou des `valve` acceptant
une position. Les sources LG officielles et SmartThinQ peuvent être combinées.

## Premier usage et migration VTherm

Laisser l'armement désactivé pendant la comparaison des températures et demandes.
VTherm peut alors continuer de piloter les équipements. Avant le pilotage réel :

1. Tester les commandes et retours d'état natifs des entités choisies dans HA.
2. Faire valider le débit minimal indépendant des têtes (bypass, ballon/circuit
   permanent adapté), le dégivrage et les temporisations par l'installateur.
3. Désactiver VTherm et toutes les automatisations qui commandent ces équipements,
   dont les anciens réglages/synchronisations de la PAC.
4. Dans les options **Sécurités**, confirmer ces validations et permettre le pilotage.
5. Activer l'interrupteur **Armement des commandes (session)** et superviser les essais.

Un redémarrage ou rechargement HA désarme le contrôleur. Les dérogations encore
valides sont conservées avec leur échéance, mais n'arment jamais les commandes.
La PAC peut conserver son dernier mode natif : observation, pause ou désarmement
signifient **arrêt des commandes**, et non extinction du chauffage.

## Fonctions livrées

- Une entité `climate` par pièce, sonde externe, plusieurs émetteurs, hystérésis,
  hors-gel et six consignes (présence, absence, nuit, vacances, manuel, solaire).
- Modes généraux temporaires et présence temporisée. Une présence indisponible
  conserve le dernier mode connu (présent au démarrage).
- Blocage rouge HP 06–22 h selon le fuseau HA, couleur inconnue bloquante par défaut,
  corrections blanc/rouge, préchauffage optionnel avant 6 h.
- Dérogation Tempo et forçage général temporisés. Le forçage relève les cibles au
  moins au niveau présence ; il ne force pas une chauffe si toutes les pièces sont satisfaites.
- Surplus réseau signé prioritaire ; sinon bilan production − consommation.
  Seuils, marge, hystérésis, qualifications et maintien solaire configurables.
- Opt-in solaire par pièce, consigne solaire exposée en `number`, autorisation
  solaire rouge configurable. Une pièce exclue du solaire reste bloquée en rouge.
- Vérification des capacités, commandes sérialisées, limitation de fréquence,
  accusés par retour d'état, minima marche/arrêt et circulation résiduelle.
- Capteurs explicatifs, notifications de défaut et diagnostics anonymisés.
- Simulateur hors ligne, tests unitaires et tests HA prévus pour Linux.

## Contrats matériels et limites

La PAC est commandée uniquement via `climate.set_hvac_mode` (`heat` ou `auto`,
et `off`). Le réglage de puissance compresseur, l'ECS, la coupure électrique et les
consignes de loi d'eau ne sont pas commandés. Le minimum marche/arrêt porte sur le
**mode chauffage HA**, pas sur une mesure du compresseur.

Une tête `climate` reçoit une consigne haute en demande et basse hors demande,
bornées à ses capacités. Cela exige une calibration : son retour de consigne
ne prouve pas l'ouverture mécanique de la vanne. Les `number` et `valve` reçoivent
une ouverture proportionnelle à l'écart de température.

En défaut (sonde, connexion, protection, eau trop chaude ou ordre non appliqué), les
commandes sont suspendues et les états physiques conservés. Les protections LG,
le hors-gel matériel et la garantie hydraulique indépendante restent indispensables.
Un défaut de commande nécessite l'acquittement, qui désarme, puis un réarmement.
Un défaut de mesure se résorbe quand les données sont de nouveau valides.

Le transport est extensible ; aucun adaptateur Modbus n'est livré dans cette version.
Le calcul solaire favorise l'autoconsommation sans garantie d'import réseau nul.

## Tableau de bord sans carte supplémentaire

Dans l'éditeur graphique Lovelace, ajouter une carte **Thermostat** par pièce,
une carte **Entités** avec les interrupteurs et le sélecteur de mode, puis une carte
**Historique** pour le surplus, la puissance PAC et le nombre de demandes. Ajouter
les capteurs Décision, Motif, État du pilotage, Tempo et Défaut. Le capteur Décision
expose le mode effectif et le mode PAC observé ; le sélecteur affiche le mode demandé.

## Développement et validation

Python 3.12+ suffit au moteur autonome. Depuis ce dossier :

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests/unit -v
.\.venv\Scripts\python.exe tools/simulate.py
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\python.exe tools/build_release.py
```

Les tests `tests/ha` utilisent le véritable framework Home Assistant et
`pytest-homeassistant-custom-component`, sur Linux et un Python compatible avec
la version HA testée. Le workflow fourni utilise Python 3.14 et les versions
disponibles de ces dépendances. Il inclut aussi hassfest. Ces jobs doivent être
exécutés et réussir avant de publier une version utilisable en production.

## Distribution HACS

Le dépôt de distribution choisi est [Macorou/HA](https://github.com/Macorou/HA),
avec `@Macorou` comme responsable. Le manifeste des sources et des archives contient
les liens vers ce dépôt et ses issues. Le projet suit la
[structure HACS](https://www.hacs.dev/docs/publish/integration/).
L'archive locale est installable par copie, indépendamment de la publication GitHub.
Pour reconstruire les archives avec ces métadonnées :

```text
python tools/build_release.py --repository https://github.com/Macorou/HA.git
```

Le suffixe de clonage `.git` est retiré des liens web générés. Cette commande peut
également préparer un autre dépôt dans le **manifeste de l'archive générée**, sans
modifier les sources. Après publication du contenu de l'archive source dans le
dépôt, exécuter la CI et créer une release. Ajouter ensuite `https://github.com/Macorou/HA`
à HACS comme
**dépôt personnalisé → Intégration**. L'inscription au catalogue HACS est une démarche distincte.

## Documentation

- [Architecture et étapes](docs/ARCHITECTURE.md)
- [Réglages et arbitrages](docs/REGLAGES.md)
- [Réception et dépannage](docs/VALIDATION.md)
- [Simulation avec entités HA fictives](examples/README.md)

Licence MIT. Les noms LG, Home Assistant, HACS et Tempo désignent leurs projets
et marques respectifs ; cette intégration est indépendante.
