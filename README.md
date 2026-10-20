# Smart Heat Manager — 0.2.0

Intégration personnalisée Home Assistant pour réguler des pièces à partir de
sondes externes, coordonner une PAC existante et arbitrer Tempo EDF et surplus
photovoltaïque. Indépendante de Versatile Thermostat. Interface française et anglaise.

**Version initiale à réceptionner sur Home Assistant et sur l'installation réelle.**
Elle démarre en observation, calcule les décisions et expose les entités sans envoyer
de commandes. Le contrôleur physique est implémenté, avec un armement explicite par
session ; aucune compatibilité matérielle LG non vérifiée n'est annoncée.

## Installation locale

1. Extraire `dist/smart_heat_manager-0.2.0.zip` dans le dossier de configuration HA.
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

### PAC autonome : consignes uniquement (0.2.0)

La PAC conserve sa régulation native par la sonde du salon. SHM ne lui envoie
**jamais** `turn_on`, `turn_off` ni `set_hvac_mode` : seul `set_temperature` est
autorisé, même en Tempo, solaire ou hors-gel. Une PAC arrêtée manuellement ne
reçoit aucune commande. Le mode natif attendu est surveillé, jamais sélectionné.

Trois entités `number` permettent de changer les consignes sans modifier le code :
**Consigne PAC normale**, **Consigne PAC Tempo réduit**, **Consigne PAC solaire**.
Elles sont persistantes et respectent la plage et le pas exposés par la PAC.
Valeurs initiales : 20 / 17 / 22 °C, à adapter avant tout armement.
Le capteur **Consigne PAC calculée** expose la cible, même en observation.
Sans demande des pièces, la consigne normale est conservée : aucun arrêt ni
abaissement automatique. Tempo rouge HP utilise la cible réduite, sans garantir
une consommation nulle ; solaire qualifié utilise la cible solaire si une pièce
autorisée est en demande. Pause ou défaut : aucun ordre, dernière consigne conservée.

Les anciens minima marche/arrêt et délais de circulation de SHM ne sont plus
appliqués : ces fonctions restent natives à la PAC. Le débit minimal indépendant
des têtes doit rester garanti, même quand toutes les pièces sont satisfaites.
La sonde du salon peut limiter la chauffe des autres pièces : ouvrir une tête
ne force pas le compresseur à démarrer. Ne pas étouffer le circuit de référence.

### Correctif 0.1.2 : température ambiante stable

Une température de pièce inchangée ne devient plus périmée au bout d'une heure.
La disponibilité déclarée par l'intégration de la sonde fait foi : les états
`unknown`, `unavailable`, absents ou les mesures invalides restent bloquants.
Activer la détection de disponibilité de la source (par exemple Zigbee2MQTT) :
SHM ne peut pas déduire la connexion d'une sonde de son seul changement de température.
Le délai de détection d'une perte dépend de cette source, pas de SHM.
Les délais des mesures de puissance, de l'eau et des protections restent inchangés.
Mettre à jour les fichiers puis redémarrer HA ; les pièces sont conservées et les
commandes restent désarmées après redémarrage. Aucun changement de réglage requis.

### Têtes SONOFF TRVZB : deux réglages de vanne

Dans les paramètres de la pièce, activer **Configurer des SONOFF TRVZB (ouverture +
fermeture)**. Dans l'écran suivant, ajouter une tête et sélectionner son `climate`,
son `number` **Valve opening degree** et son `number` **Valve closing degree**.
Répéter pour les autres radiateurs de la pièce, puis choisir **Valider la pièce**.
Ne pas sélectionner ces mêmes entités dans « Autres têtes / vannes directes ».

Les réglages sont coordonnés : ouverture `P`, fermeture `100−P` (30 % / 70 % par
exemple). La fermeture complète demande 0 % / 100 %. Les deux réglages sont confirmés
avant le mode Chauffage de la tête et avant une consigne PAC. Il ne s'agit pas de
deux radiateurs indépendants ni d'une mesure de position mécanique.

Ce profil exige un [TRVZB compatible (micrologiciel 1.1.4 ou supérieur)](https://www.zigbee2mqtt.io/devices/TRVZB.html#valve-opening-degree-numeric).
Désactiver le contrôle intelligent natif de la tête s'il est disponible ; le profil
ne modifie pas lui-même cette option ni le micrologiciel. Valider les mouvements
réels et la calibration de la tête avant de confirmer les capacités de pilotage.

Pour mettre à jour depuis 0.1.0 : télécharger de nouveau l'intégration dans HACS,
redémarrer HA, puis modifier les pièces depuis les options. Les pièces existantes
sont conservées ; leurs TRVZB doivent être associées dans le nouveau menu dédié.
Le rechargement conserve le retour en observation.

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

- Une entité `climate` par pièce, sonde externe, plusieurs émetteurs (dont les paires SONOFF TRVZB), hystérésis,
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
  accusés par retour d'état et consignes PAC sans aucun ordre marche/arrêt.
- Capteurs explicatifs, notifications de défaut et diagnostics anonymisés.
- Simulateur hors ligne, tests unitaires et tests HA prévus pour Linux.

## Contrats matériels et limites

La PAC reçoit uniquement une température ambiante via `climate.set_temperature`,
jamais une commande de mode ni d'allumage/extinction. Le réglage de puissance
compresseur, l'ECS, la coupure électrique et la loi d'eau ne sont pas commandés.
La PAC conserve la modulation, les anti-cycles et la circulation native.

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
