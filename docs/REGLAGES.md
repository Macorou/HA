# Réglages et comportement

## Pièces

Les températures doivent rester entre 5 et 35 °C et au-dessus du hors-gel. Les valeurs
initiales sont des points de départ, pas des prescriptions pour l'installation.
Une même tête ne peut appartenir à deux pièces. La sonde ne peut être l'un des
actionneurs, ni la PAC. Les entités créées par Smart Heat Manager sont interdites
comme entrées pour éviter une boucle de régulation.

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
| Sous la température hors-gel | Demande prioritaire sur Tempo, sous réserve des minima PAC |
| Forçage général / dérogation Tempo | Suspension des règles économiques jusqu'à échéance |
| Rouge HP, sans dérogation | Aucune demande normale ; solaire uniquement si explicitement permis |
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
termine l'élévation solaire ; les minima physiques PAC continuent de s'appliquer.
Il ne s'agit jamais d'une consigne directe de puissance compresseur.

## Temporisations PAC et défauts

Valeurs initiales : minimum marche 20 min, minimum arrêt 10 min, demande stable
2 min, circulation après arrêt 3 min, intervalle commande 1 min, confirmation 3 min.
Ces valeurs sont à valider sur l'installation. Au premier relevé, le minimum du mode
observé recommence de façon conservatrice, faute d'historique compresseur fiable.

Les têtes sont confirmées avant l'ordre de démarrage. Pendant la marche normale,
les pièces satisfaites peuvent fermer leurs têtes puisque le débit indépendant
a été validé. Lorsqu'il n'y a plus de demande, les dernières ouvertures sont
conservées pendant le minimum marche, l'arrêt confirmé et le délai de circulation.

Les ordres non appliqués sont signalés, sans boucle de tentatives. Le bouton
Acquitter efface le verrou de commande et désarme ; vérifier la cause puis réarmer.
La disponibilité des capteurs utilise la date du dernier rapport reçu, y compris
si sa valeur est restée stable. Le délai maximal est configurable.

Ce délai concerne les mesures de température/puissance et la surveillance. Les
couleurs Tempo disposent de 48 h puisqu'elles changent quotidiennement ; les helpers
statiques HA restent valides tant qu'ils sont disponibles. La PAC et les têtes sont
contrôlées par leur disponibilité déclarée par leur intégration. Les temporisations
sont calculées en UTC pour rester correctes lors des changements d'heure.
