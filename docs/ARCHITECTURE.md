# Architecture et plan de réalisation

Smart Heat Manager 0.3.0 est une intégration locale d'orchestration : elle exploite
les états et services des intégrations déjà installées, sans identifiants LG,
sans dépendance VTherm et sans accès direct au cloud.

## Découpage

| Module | Responsabilité |
| --- | --- |
| `models.py`, `const.py` | Configuration versionnée, instantanés et résultats |
| `presence.py` | Présence temporisée et conservation du dernier état valide |
| `tempo.py` | Couleur normalisée, fenêtre locale 06–22 h et anticipation |
| `solar.py` | Bilan électrique signé, restitution de la charge PAC, hystérésis |
| `regulation.py` | Sonde externe, consignes, hystérésis par pièce |
| `engine.py` | Arbitrage explicite et décisions explicables sans effets de bord |
| `adapters.py` | Commandes climate/number/valve, capacités vérifiées |
| `emitters.py` | Groupes physiques : vanne simple ou SONOFF TRVZB avec ouverture, fermeture et climate |
| `controller.py` | Sérialisation, accusés d'état, consignes PAC exclusivement |
| `coordinator.py` | Événements HA, échéances, persistance, mode observation |
| `config_flow.py` | Installation et options : pièces ajoutables/modifiables/supprimables |
| Plateformes | Climate par pièce, capteurs, interrupteurs, nombres, sélection de mode |
| `diagnostics.py` | Décisions, capacités et commandes, identifiants anonymisés |

## Modèle de configuration

Une entrée unique représente l'installation, avec un dictionnaire `settings` et
une liste `rooms`. Chaque pièce possède un UUID stable, une sonde externe et des
actionneurs ; renommer une pièce ne change pas ses identifiants d'entité.
L'assistant natif utilise des sélecteurs d'entités et de nombres. Les options
remplacent la configuration effective et rechargent l'entrée. Les préférences
quotidiennes, le choix d'armement et le journal de commandes sont persistés.
Les dérogations conservent leurs dates de fin UTC.

## Machine à états

Depuis 0.6.0, `overrides.pump_target` stocke une cible et échéance propres à
l'entité PAC (`entity_id`). `Decision.pump_profile` distingue ce profil PAC du
profil des pièces `Decision.mode`. Les dérogations `room_<id>` sont inchangées.
Le sélecteur PAC auto ne touche jamais aux dérogations des pièces.

Le bus HA `call_service` capture les demandes utilisateur explicites sur la PAC,
pas les rapports cloud. Les contextes des commandes SHM sont identifiés et bornés
en mémoire ; aucun écho n'active ou ne prolonge le mode manuel. Les droits de
commande PAC sont vérifiés avant adoption, car l'événement HA précède ces droits
dans le dispatch natif. La dernière demande valide remplace l'intention automatique
en attente sans acquitter un défaut verrouillé. Une intention manuelle encore en
file inhibe une écriture PAC automatique concurrente ; la demande native n'est pas
dupliquée tant que son retour est attendu. La dérogation est persistée avant
évaluation. Les protections, l'armement et la politique Tempo restent prioritaires.

Priorité : défaut matériel ou donnée essentielle manquante → suspension des
commandes ; pause automatique → aucune commande ; hors-gel → besoin prioritaire ;
dérogation économique temporisée → autorisation ; Tempo rouge HP → blocage ;
besoin normal → chauffe ; surplus durable → élévation bornée des consignes ; sinon repos.

Le résultat logique (`fault`, `paused`, `frost`, `tempo_blocked`, `heating`,
`solar_heating`, `idle`) est distinct du transport (`observation`, `running`,
`pump_off`, `adjusting_setpoint`, `opening_emitters`, `emitter_fault`, `suspended`, `command_fault`).
Une demande logique ne prouve jamais que le compresseur tourne.

Les commandes d'un même émetteur restent séquencées et confirmées, mais depuis
0.5.1 leurs accusés ne conditionnent plus la consigne de la PAC autonome. Un
`command_not_applied` visant une tête configurée suspend toutes les commandes des
têtes, sans suspendre la PAC indépendante. Le défaut reste verrouillé et persisté,
même si un retour tardif correspond enfin à l'ordre. Un défaut PAC est prioritaire
sur un défaut tête ; toute erreur globale, inconnue ou de journal reste bloquante.
La seule exception marche/arrêt est la fenêtre rouge Tempo :
arrêt, puis reprise d'un arrêt attribué à SHM et confirmé par retour d'état.
Une barrière dans le transport exige une autorisation éphémère de ce contrôleur,
revérifie la fenêtre/dérogation, l'armement, les protections et la propriété de
l'arrêt avant tout changement de mode. Les consignes sont aussi bloquées pendant
l'arrêt Tempo pour éviter qu'un appareil ne se réveille par une écriture de cible. En
défaut global il suspend les ordres et conserve les états physiques. La régulation native,
les anti-cycles, l'ECS et la loi d'eau restent à la charge de la PAC. Les têtes
peuvent fermer lorsque les pièces sont satisfaites : le débit indépendant est requis.

La cible du profil effectif (présence, absence, nuit, vacances, manuel) est conservée
sans demande ; les jours rouges confirmés demandent un arrêt. La couleur inconnue
peut plafonner cette cible à la consigne de repli ; le solaire qualifié
peut la relever avec une pièce éligible en demande. Les sept cibles sont des
préférences persistantes modifiables en `number`. Le champ historique
`pump_normal_target` conserve l'identité de la consigne présence et sa valeur.
La pause et les défauts des mesures/protections produisent une cible nulle
(aucun ordre, pas une consigne zéro). Un défaut d'accusé tête n'annule pas cette cible.

Le journal persistant `runtime.tempo_control` enregistre l'entité, le mode, la fin
de fenêtre et la confirmation de l'arrêt. Une intention seule ne permet jamais de
rallumer après un redémarrage. Les transitions externes `off → mode attendu`
pendant les heures rouges créent une dérogation jusqu'à 22 h ; les acquittements
des propres reprises du contrôleur ne prolongent pas une dérogation temporaire.
Depuis 0.5.0, `runtime.armed_requested` mémorise le choix explicite de l'opérateur.
Le redémarrage ou rechargement conserve ce choix, mais les commandes attendent
que HA ait terminé son démarrage et que toutes les autorisations et mesures
soient valides. Une préférence absente ou invalide ne vaut jamais activation.
Le journal `runtime.control_state` conserve les défauts verrouillés, les ordres
non acquittés et l'intervalle de commande. Chaque intention est persistée avant
l'envoi physique. Un redémarrage n'efface donc ni un défaut ni un accusé en attente.
Une transition Tempo interrompue sans confirmation reste ambiguë et bloque la
commande, sans autoriser une reprise. Un arrêt explicite ou le bouton d'acquittement
avec désarmement enregistre l'arrêt. Les protections suspendent les commandes
sans effacer le choix d'armement.

## Électricité solaire

Le bilan réseau est prioritaire. Convention import positif : surplus signé =
`-réseau` ; injection positive : surplus = `réseau`. Sinon surplus = production −
consommation maison (moins PAC uniquement si explicitement exclue de cette mesure).
Pendant la chauffe, la charge PAC mesurée est réintégrée pour mesurer la puissance
disponible pour cette même charge. Un import réseau reste négatif dans le bilan :
ne pas le tronquer avant cette correction. Sans mesure PAC, maintien conservateur
sur le surplus net. Donnée solaire invalide : aucun nouveau préchauffage.

## Validations terrain nécessaires

- Mode natif attendu `heat` ou `auto`, plage/pas de température et retours d'état LG.
- Ouverture des têtes : pourcentage natif ou consigne de substitution à calibrer ;
  régler une consigne élevée ne constitue pas une preuve d'ouverture physique.
- Débit minimal, ballon tampon/bypass ou circuit permanent, dégivrage, circulation
  résiduelle, adéquation des minima marche/arrêt : validation par l'installateur.
- Un signal de protection matériel peut inhiber les commandes. La garantie de débit
  doit rester indépendante du logiciel et du cloud.
- Entité Tempo : doit représenter la couleur applicable à l'heure observée ; le
  préchauffage utilise « demain » le soir et « aujourd'hui » après minuit avant 6 h.
- Attribution du compteur PAC (chauffage seul ou ECS comprise) et convention réseau.

## Étapes et réception

1. Architecture, moteur indépendant et tests de scénarios.
2. Assistant, options, plateformes natives, diagnostics et persistance.
3. Contrôleur réel inhibé par défaut ; vérification des capacités et retours d'état.
4. Tests automatisés, simulateur, documentation et archive installable.
5. Sur HA cible : observation, comparaison VTherm, désactivation des anciens pilotes,
   validation hydraulique, armement, réception supervisée ; retrait VTherm ensuite.

Le dépôt de distribution choisi est `https://github.com/Macorou/HA`, avec
`@Macorou` comme responsable. Les métadonnées HACS sont configurées pour cette
destination ; leur présence ne prouve pas que les fichiers ont déjà été publiés.
Le paquet local peut être installé par copie. Les tests locaux ne remplacent pas
une réception sur l'installation.

## Références vérifiées

- https://developers.home-assistant.io/docs/config_entries_options_flow_handler/
- https://developers.home-assistant.io/docs/core/entity/climate/
- https://developers.home-assistant.io/docs/core/integration/diagnostics/
- https://www.hacs.dev/docs/publish/integration/
