# Réglages et comportement

## Pièces

Les températures doivent rester entre 5 et 35 °C et au-dessus du hors-gel. Les valeurs
initiales sont des points de départ, pas des prescriptions pour l'installation.
Une même tête ne peut appartenir à deux pièces. La sonde ne peut être l'un des
actionneurs, ni la PAC. Les entités créées par Smart Heat Manager sont interdites
comme entrées pour éviter une boucle de régulation.

Pour les SONOFF TRVZB, utiliser exclusivement le menu dédié de la pièce : associer
le climate, l'ouverture et la fermeture de chaque tête. Une paire compte comme un
émetteur logique. Chaque pourcentage P commande ouverture=P et fermeture=100−P ;
la consigne de température native de la tête n'est pas modifiée par ce profil.
Les confirmations portent sur les trois entités. Une seule indisponible suspend
les commandes ; un réglage non appliqué empêche l'ajustement PAC et verrouille un
défaut après le délai habituel. Les deux réglages restent coordonnés pendant le
pilotage par consigne PAC. Ils ne sont jamais assimilés à une
preuve d'ouverture mécanique. Le constructeur ne documente ces degrés qu'à partir
du micrologiciel 1.1.4 ; vérifier aussi que le contrôle intelligent natif n'interfère
pas. Le profil ne déclenche ni recalibration, ni mise à jour, ni désactivation du
hors-gel matériel. Effectuer la réception mécanique avec l'installation réelle.

Une demande commence sous cible − hystérésis et se termine au-dessus de cible +
hystérésis. Les actionneurs proportionnels reçoivent une ouverture bornée à 0–100 %,
avec minimum de demande 10 %. Pour les têtes climate, calibrer la consigne haute
pour obtenir la chauffe, et la basse pour réduire la chauffe sans supprimer leur
hors-gel natif. Il n'y a pas d'apprentissage automatique de l'inertie thermique.

L'arrêt d'une pièce conserve le hors-gel logiciel lorsque le contrôleur est armé et
les automatismes actifs. Un arrêt général des automatismes suspend tous les ordres,
y compris ce hors-gel logiciel.

## Priorités et dérogations

| Situation | Comportement |
| --- | --- |
| Protection, donnée essentielle absente, température d'eau haute | Suspension des commandes et alerte |
| Automatismes désactivés | Suspension des commandes, sans extinction native |
| Sous la température hors-gel | Demande hors-gel, sans relance automatique de la PAC en rouge confirmé |
| Forçage général / dérogation Tempo | Suspension des règles économiques jusqu'à échéance |
| Rouge HP confirmé, sans dérogation | Arrêt PAC confirmé, puis reprise à partir de 22 h si l'arrêt appartient à SHM |
| Besoin normal | Consigne du mode effectif |
| Surplus qualifié | Cible solaire pour les seules pièces autorisées |

Les modes généraux non automatiques, la consigne manuelle d'une pièce, le forçage
et la dérogation Tempo expirent après la durée configurée au moment de l'activation.
Les échéances sont affichées dans les attributs. Changer la durée ne modifie pas
les échéances déjà créées. Choisir le mode général Auto annule les dérogations de
mode, de température et de Tempo. Le préréglage Auto d'une pièce annule sa consigne
temporaire. Un préréglage Présent/Nuit/etc. sur une pièce est une consigne temporaire
et est affiché comme Manuel pendant sa durée.

Les interrupteurs solaire/automatismes, l'activation des pièces et les réglages
`number` sont des préférences persistantes, sans échéance. Ils ne sont pas réinitialisés
par le mode Auto. Les réglages numériques quotidiens prennent priorité sur les valeurs
des options ; les modifier depuis l'entité `number` pour changer cette priorité.

## Tempo

Le moteur utilise le fuseau Home Assistant (`Paramètres → Système → Général`),
pas celui du navigateur. La restriction est active de 06:00 inclus à 22:00 exclu.
Les textes bleu/blue, blanc/white et rouge/red sont reconnus. Les sources booléennes
« rouge ou non » ne suffisent pas à distinguer blanc/bleu et sont exclues du sélecteur.

En rouge confirmé, le contrôleur armé demande `off` de 6 h à 22 h. À 22 h, il ne
restaure le mode attendu que si SHM a enregistré et confirmé son propre arrêt.
Une PAC déjà en `off` n'acquiert pas cette autorisation de reprise.
La dérogation Tempo temporaire permet une reprise pendant sa durée ; une relance
par le bouton natif, observée dans HA, crée une dérogation jusqu'à 22 h. Un arrêt
manuel après cette relance annule la reprise connue. Les acquittements des ordres
SHM sont distingués des relances externes, pour ne pas étendre les dérogations.
Couleur inconnue : pas d'arrêt automatique présenté comme rouge confirmé ; le
plafond de repli peut s'appliquer si le blocage sur couleur inconnue est activé.
Le solaire et le hors-gel logiciel ne contournent pas l'arrêt rouge confirmé.
Les protections matérielles restent indispensables ; arrêt chauffage ne signifie
pas coupure électrique ni garantie d'absence de consommation auxiliaire.

Vérifier la sémantique de l'entité fournie : certaines intégrations changent la
couleur à minuit, d'autres à 6 h. Pour anticiper avant 6 h, la source Aujourd'hui doit
déjà annoncer le jour civil à venir après minuit. Une source conservant la veille
jusqu'à 6 h nécessite une entité adaptée en amont. Le préchauffage n'infère pas une
couleur à partir d'une ancienne valeur indisponible.

Le préchauffage optionnel s'effectue entre l'heure choisie (0–5 h) et 6 h si Aujourd'hui
est rouge. L'augmentation est bornée par la consigne solaire de chaque pièce. La
couleur de demain est exposée dans la configuration et préparée pour des extensions
de préchauffage en soirée ; l'interface de cette version privilégie l'anticipation nocturne.

## Solaire

| Source | Bilan signé utilisé |
| --- | --- |
| Réseau import positif | `surplus net = -réseau` |
| Réseau export positif | `surplus net = réseau` |
| Production et maison incluant la PAC | `surplus net = production - maison` |
| Production et maison excluant la PAC | `surplus net = production - maison - PAC` |

Quand la PAC est déjà en mode chauffage, sa puissance mesurée est ajoutée au bilan
net pour calculer ce qui est disponible **pour elle**. La marge est ensuite retirée.
Exemple : injection 500 W, PAC 3 000 W, marge 200 W → budget de maintien 3 300 W.
Un import de 1 000 W donne au contraire un budget de 1 800 W, pas 2 800 W.

La source réseau configurée mais invalide autorise le repli vers production/maison
si ces deux mesures sont valides. Si la maison exclut la PAC et que sa puissance
manque, le bilan ne peut pas être établi. Sans mesure PAC, aucune compensation
n'est ajoutée : le comportement est conservateur et peut arrêter le préchauffage.
Un compteur PAC incluant l'ECS peut surestimer la charge chauffage : sélectionner
une mesure adaptée et valider les résultats avant usage.

Activation après `seuil démarrage + hystérésis` pendant la durée de qualification.
Fin après passage sous `maintien − hystérésis` pendant le délai d'arrêt, à condition
que la durée minimale solaire soit écoulée. La perte d'une source indispensable
  termine l'élévation solaire ; la PAC conserve ses protections et temporisations natives.
Il ne s'agit jamais d'une consigne directe de puissance compresseur.

## PAC autonome et défauts

Hors exception Tempo documentée ci-dessus, la PAC reçoit seulement `set_temperature`.
Le transport interdit toute commande de mode sans autorisation Tempo ponctuelle
et propriété confirmée pour la reprise. Un arrêt manuel n'est pas repris par
une demande ordinaire, le hors-gel logiciel ou le solaire.

Les nombres **Consigne PAC présence**, **absence**, **nuit**, **vacances**, **manuel**,
**repli Tempo inconnu** et **solaire** sont modifiables quotidiennement et persistés.
Leurs valeurs initiales sont 20 / 17 / 18 / 16 / 20 / 17 / 22 °C : les vérifier
avant l'armement. La consigne présence conserve la valeur et l'identifiant de
l'ancienne consigne normale. Les limites et le pas suivent
les capacités natives ; les valeurs incompatibles sont refusées, pas corrigées en
silence. La PAC suit le même mode effectif que les pièces : en automatique,
présence/absence après temporisation (si activée), sinon présence. Le mode général
temporaire permet aussi absence/nuit/vacances/manuel ; sa durée et son retour à
l'automatique restent inchangés. Sans demande des pièces la cible du profil actif
est conservée. Le repli sur couleur inconnue plafonne la cible sans remonter une
absence/vacances plus basse. Les jours rouges confirmés demandent l'arrêt, pas ce plafond.
Les corrections blanc/rouge s'appliquent au profil PAC et doivent respecter le
pas/plage natifs. Le forçage général relève au moins au niveau présence.
Le préchauffage avant un jour rouge peut relever la cible du profil de l'écart
configuré, sans dépasser la cible solaire ni abaisser une consigne plus haute.

Les têtes sont confirmées avant l'ajustement PAC. Elles peuvent fermer dès que
les pièces sont satisfaites ; le circuit de référence et le débit hydraulique
indépendant sont indispensables. La PAC gère elle-même la modulation et les
minima marche/arrêt. Les anciens réglages `min_on`, `min_off`, `demand_delay` et
`drain_delay` peuvent subsister dans les anciennes données mais sont ignorés.
SHM conserve l'intervalle de commande (60 s initialement) et les accusés (180 s).

Les ordres non appliqués sont signalés, sans boucle de tentatives. Le bouton
Acquitter efface le verrou de commande et désarme ; vérifier la cause puis réarmer.
Les sondes de température des pièces utilisent la disponibilité déclarée par leur
intégration source, sans expiration sur l'horodatage HA : une sonde MQTT peut émettre
une valeur identique sans actualiser cet horodatage. Les états absents, `unknown`,
`unavailable`, les unités incompatibles et les températures invalides restent
bloquants. Activer et vérifier la détection de disponibilité dans l'intégration
source (par exemple Zigbee2MQTT). Son délai de détection dépend de sa configuration ;
SHM ne dispose pas d'un heartbeat matériel à partir du seul état de température.

Le délai maximal configurable utilise le dernier rapport HA pour les mesures de
puissance et la surveillance (températures d'eau et protection). Il n'est pas étendu
par ce correctif. Les couleurs Tempo disposent de 48 h puisqu'elles changent
quotidiennement ; les helpers statiques HA restent valides tant qu'ils sont
disponibles. La PAC et les têtes sont contrôlées par leur disponibilité déclarée
par leur intégration. Les temporisations sont calculées en UTC pour rester
correctes lors des changements d'heure.
