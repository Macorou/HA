# Réception et dépannage

## État des vérifications

Les tests locaux vérifient le moteur et le contrôleur avec un transport simulé.
La suite HA réelle est distincte : elle doit réussir sur Linux, puis une réception
supervisée doit être réalisée sur les entités choisies. La compatibilité annoncée
dans `hacs.json` est une cible minimale, pas une certification de toutes les versions.

## Scénarios de réception sur HA

En observation, comparer les cibles, états et motifs avec les attentes pour chaque
pièce. Tester bleu, blanc, rouge HP/HC, expiration de la dérogation Tempo, consigne
manuelle, variations du surplus et perte d'une mesure. Utiliser les entités fictives
du dossier `examples` si l'installation réelle ne doit pas encore être sollicitée.

Pendant un essai physique supervisé :

1. Vérifier l'ouverture de chaque tête et son retour, puis les commandes de
   température PAC sans aucun ordre LG marche/arrêt/mode. Consigner les délais réels.
2. Comparer température externe, température de la tête et fonctionnement mécanique.
3. Contrôler plusieurs pièces puis l'absence de demande : la PAC conserve son mode
   et sa cible normale. Relever le débit réel et le dégivrage avec l'installateur.
4. Vérifier les trois consignes, le respect d'un arrêt manuel de la PAC et la
   limitation des commandes. Observer la modulation et les anti-cycles natifs.
5. Provoquer une indisponibilité simulée, vérifier l'alerte et l'absence de spam d'ordres.
6. Vérifier qu'un redémarrage désarme et laisse les protections natives opérationnelles.
7. Tester le retour en observation et la reprise contrôlée par l'ancien système si nécessaire.

Ne supprimer définitivement VTherm qu'après réception complète et sauvegarde HA.

## Diagnostics

Depuis la fiche de l'intégration, télécharger les diagnostics. Ils contiennent
la configuration anonymisée, les décisions par pièce, les temporisations en attente,
les ordres non confirmés et l'état observé. Les identifiants d'entité sont remplacés
par des empreintes, les noms de pièce, remarques et attributs bruts sont retirés.
Les journaux locaux gardent les identifiants pour permettre le dépannage ; ne pas
les publier sans vérification.

| Motif | Vérification |
| --- | --- |
| `room_sensor_unavailable` | Disponibilité déclarée par la source, unité °C/°F, valeur valide de la sonde externe |
| `pump_unavailable` | Intégration LG, cloud et état climate |
| `actuator_unavailable` | Disponibilité de toutes les têtes configurées |
| `hardware_protection` | Signal ON choisi dans Protection ; respecter le fonctionnement natif |
| `monitor_unavailable` | Sonde d'eau ou signal de protection configuré mais invalide |
| `water_temperature_high` | Température et seuil d'eau ; examen de l'installation |
| `pump_modes_not_supported` | `heat`/`auto` choisi et `off` doivent être exposés |
| `pump_external_mode` | PAC passée en refroidissement ou autre mode externe : pas d'écrasement automatique |
| `command_not_applied` | Retour d'état cloud, délai de confirmation, calibration |
| `number_must_be_percentage_0_100` | Choisir une vraie entité d'ouverture de vanne en % |
| `tempo_unknown` | Source de couleur et convention de changement de jour |

`minimum_off`, `minimum_on`, `opening_emitters`, `stopping` et `draining` sont des
états de séquencement normaux. L'interrupteur de restriction Tempo indique la fenêtre
tarifaire, même si une dérogation ou le hors-gel autorise exceptionnellement une demande.

### Régression : température stable (0.1.2)

Une pièce doit rester disponible après plus d'une heure à température identique,
tant que la sonde reste disponible dans HA. Simuler ensuite un état `unavailable`,
`unknown`, absent ou invalide sur une sonde fictive : le thermostat doit devenir
indisponible, la demande PAC doit être annulée et les commandes bloquées. Le retour
à une mesure valide restaure le thermostat, sans armer le pilotage.
Les mesures de puissance et la surveillance de l'eau/protection doivent toujours
être rejetées après leur délai maximal. Ces scénarios sont couverts dans `tests/ha`.

## Retrait et restauration

Désarmer, choisir la stratégie de reprise native/ancienne régulation, puis supprimer
l'entrée dans Appareils et services. Les préférences stockées par l'intégration
sont supprimées avec l'entrée ; les entités sources et leurs réglages ne sont pas
modifiés au retrait. Supprimer ensuite le dossier du composant et redémarrer HA.
Une sauvegarde HA permet de restaurer l'entrée et ses options.
