# Smart Heat Manager — 0.6.0

Depuis 0.6.0, les boutons +/- de la carte native PAC créent une dérogation
temporaire **PAC uniquement** pour la durée configurée. Le sélecteur **Mode PAC
temporaire** affiche Manuel et permet le retour immédiat à Automatique, sans
effacer les dérogations des pièces. Les thermostats SHM des pièces gardent chacun
leur propre consigne manuelle. Aucun de ces réglages ne passe toute la maison en manuel.

La détection PAC porte sur les appels HA `climate.set_temperature` d'un utilisateur
authentifié autorisé à commander la PAC. Les retours cloud, valeurs restaurées,
commandes SHM et automatismes sans utilisateur ne créent pas de dérogation.
La modification d'une consigne seule ne contourne pas Tempo et n'autorise pas
une remise en marche ; les protections et l'armement restent inchangés.

Correctif 0.5.1 : un ordre de tête non confirmé ne fige plus les consignes de la
PAC autonome. Le défaut reste visible et verrouillé, et toutes les commandes des
têtes restent suspendues jusqu'à vérification et acquittement explicite.

Intégration personnalisée Home Assistant pour réguler des pièces à partir de
sondes externes, coordonner une PAC existante et arbitrer Tempo EDF et surplus
photovoltaïque. Indépendante de Versatile Thermostat. Interface française et anglaise.

**Version initiale à réceptionner sur Home Assistant et sur l'installation réelle.**
Au premier usage, elle démarre en observation sans envoyer de commandes.
Le contrôleur physique utilise un choix d'armement explicite, mémorisé après les
redémarrages ; aucune compatibilité matérielle LG non vérifiée n'est annoncée.

## Installation locale

1. Extraire `dist/smart_heat_manager-0.3.0.zip` dans le dossier de configuration HA.
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

### PAC autonome avec exception Tempo (0.3.0)

Hors exception Tempo, la PAC conserve sa régulation native par la sonde du salon :
SHM ne règle que la température, sans ordres marche/arrêt liés aux demandes des
pièces. **En jour rouge confirmé de 6 h à 22 h**, SHM demande le mode `off` puis,
à partir de 22 h, restaure le mode natif attendu uniquement s'il a lui-même arrêté
la PAC et reçu la confirmation. Une PAC déjà arrêtée manuellement n'est pas rallumée.

Deux relances manuelles sont possibles pendant la période rouge :

- **Dérogation Tempo temporaire** : autorise la reprise d'une PAC arrêtée par SHM
  pendant la durée choisie. À expiration avant 22 h, nouvel arrêt Tempo.
- **Bouton Marche habituel de la PAC** : si HA remonte le passage de `off` au mode
  attendu, SHM respecte cette relance jusqu'à 22 h. L'interrupteur de dérogation
  reflète cette autorisation et son échéance. Une relance externe/automatisée qui
  apparaît comme ce même passage est également respectée : désactiver les anciens
  pilotes avant l'armement, pour éviter qu'ils ne contournent involontairement Tempo.

Un arrêt manuel après une relance annule la reprise automatique connue de SHM.
Le logiciel doit être armé, actif, sans défaut global et HA doit fonctionner pour envoyer
ces ordres. Depuis 0.5.0, le choix d'armement est mémorisé : le redémarrage attend
la fin du démarrage de HA et des entrées valides avant de reprendre les commandes.
Il ne s'agit pas d'une coupure électrique ; les protections natives restent actives.

Les consignes PAC sont des entités `number` persistantes, modifiables sans code :
**présence**, **absence**, **nuit**, **vacances**, **manuel**, **repli Tempo inconnu** et
**solaire**. Valeurs initiales : 20 / 17 / 18 / 16 / 20 / 17 / 22 °C, à adapter
avant l'armement dans les limites et le pas exposés par la PAC.
La PAC suit le même mode effectif que les pièces. En automatique, la présence
temporisée choisit présence/absence si elle est configurée ; sinon présence.
Depuis la version 0.4.0, le **Planning nuit** permet un passage quotidien automatique
au profil nuit, avec les entités horaires **Début de nuit** et **Fin de nuit**.
Les valeurs initiales sont 22 h et 7 h ; le planning est désactivé par défaut pour
préserver le comportement existant. Ces préférences persistent après redémarrage.
La plage suit l'heure locale de HA, peut traverser minuit, commence à l'heure de
début incluse et finit à l'heure de fin exclue (réévaluation au plus tard sous 15 s).
Des horaires identiques donnent une plage vide. Les dérogations de mode explicites
et l'absence détectée restent prioritaires. Après une dérogation, Auto reprend le
planning courant ; à la fin de la nuit, retour à la gestion présence/absence.
Les consignes Nuit existantes de chaque pièce et de la PAC sont utilisées, sans
confondre ces valeurs entre elles. Les priorités Tempo, solaire, hors-gel et
sécurité restent inchangées. Le planning n'arme jamais le pilotage : en observation,
seul le calcul change, aucun ordre physique n'est envoyé.
Les autres profils se choisissent avec le mode général temporaire, dont la durée
est réglable. À l'échéance, retour automatique, comme pour les pièces.
L'ancien réglage « normale » devient « présence » : identifiant et valeur conservés.
Le capteur **Consigne PAC calculée** expose la cible, même en observation.
Sans demande des pièces, la consigne du profil actif est conservée : aucun arrêt ni
abaissement automatique. La consigne de repli ne s'applique qu'au blocage sur une
couleur inconnue : ce n'est plus la stratégie des jours rouges confirmés.
Le solaire qualifié utilise la cible solaire si une pièce
autorisée est en demande, sans abaisser une cible de profil plus élevée.
Les corrections blanc/rouge et le forçage général s'appliquent aussi à la PAC.
Ils doivent rester compatibles avec la plage et le pas natifs (sinon commandes
suspendues, pas de consigne arrondie en silence).
Pause ou défaut global : aucun ordre, dernière consigne conservée.
Un défaut d'accusé de tête identifié suspend les têtes, pas le suivi indépendant
des profils de la PAC ; un défaut PAC reste bloquant pour l'ensemble.
Le solaire et le hors-gel logiciel ne relancent pas automatiquement la PAC pendant
les heures rouges confirmées ; une dérogation manuelle est nécessaire. Vérifier
le risque de gel avec l'installateur et conserver les protections natives.

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
commandes suivent désormais le choix d'armement mémorisé (depuis 0.5.0).

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
Le rechargement conserve désormais le choix d'armement mémorisé ; désarmer
explicitement avant de changer l'installation ou de comparer un autre régulateur.

## Premier usage et migration VTherm

Laisser l'armement désactivé pendant la comparaison des températures et demandes.
VTherm peut alors continuer de piloter les équipements. Avant le pilotage réel :

1. Tester les commandes et retours d'état natifs des entités choisies dans HA.
2. Faire valider le débit minimal indépendant des têtes (bypass, ballon/circuit
   permanent adapté), le dégivrage et les temporisations par l'installateur.
3. Désactiver VTherm et toutes les automatisations qui commandent ces équipements,
   dont les anciens réglages/synchronisations de la PAC.
4. Dans les options **Sécurités**, confirmer ces validations et permettre le pilotage.
5. Activer l'interrupteur **Armement des commandes (mémorisé)** et superviser les essais.

Un redémarrage ou rechargement HA conserve le choix d'armement. Les dérogations encore
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
  accusés par retour d'état et consignes PAC avec une seule exception marche/arrêt : Tempo.
- Capteurs explicatifs, notifications de défaut et diagnostics anonymisés.
- Simulateur hors ligne, tests unitaires et tests HA prévus pour Linux.

## Contrats matériels et limites

La PAC reçoit une température ambiante via `climate.set_temperature`. La seule
exception de mode est l'arrêt Tempo et la reprise autorisée d'un arrêt SHM confirmé,
via `climate.set_hvac_mode` ; `turn_on`/`turn_off` ne sont jamais utilisés. Le réglage de puissance
compresseur, l'ECS, la coupure électrique et la loi d'eau ne sont pas commandés.
La PAC conserve la modulation, les anti-cycles et la circulation native.

Une tête `climate` reçoit une consigne haute en demande et basse hors demande,
bornées à ses capacités. Cela exige une calibration : son retour de consigne
ne prouve pas l'ouverture mécanique de la vanne. Les `number` et `valve` reçoivent
une ouverture proportionnelle à l'écart de température.

En défaut global (sonde, connexion, protection, eau trop chaude ou ordre PAC non appliqué), les
commandes sont suspendues et les états physiques conservés. Les protections LG,
le hors-gel matériel et la garantie hydraulique indépendante restent indispensables.
Un défaut de commande nécessite l'acquittement, qui désarme, puis un réarmement.
Un défaut de mesure se résorbe quand les données sont de nouveau valides.
Seul `command_not_applied` visant une entité de tête actuellement configurée est
isolé : la PAC suit encore ses profils et sa politique Tempo, sous les mêmes
protections. Une confirmation tardive ne relance pas les têtes. Un journal invalide,
un défaut de transport non attribuable ou une entité inconnue ne sont jamais isolés.

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
