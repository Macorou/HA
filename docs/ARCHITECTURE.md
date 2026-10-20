# Architecture et plan de réalisation

Smart Heat Manager 0.2.0 est une intégration locale d'orchestration : elle exploite
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
quotidiennes et dérogations sont stockées avec leurs dates de fin UTC ; l'armement
des commandes n'est jamais persisté.

## Machine à états

Priorité : défaut matériel ou donnée essentielle manquante → suspension des
commandes ; pause automatique → aucune commande ; hors-gel → besoin prioritaire ;
dérogation économique temporisée → autorisation ; Tempo rouge HP → blocage ;
besoin normal → chauffe ; surplus durable → élévation bornée des consignes ; sinon repos.

Le résultat logique (`fault`, `paused`, `frost`, `tempo_blocked`, `heating`,
`solar_heating`, `idle`) est distinct du transport (`observation`, `running`,
`pump_off`, `adjusting_setpoint`, `opening_emitters`, `suspended`, `command_fault`).
Une demande logique ne prouve jamais que le compresseur tourne.

Le contrôleur confirme les émetteurs avant de modifier la température ambiante
demandée à la PAC. La PAC n'est jamais allumée, éteinte ou changée de mode par SHM.
Une barrière supplémentaire dans le transport interdit tout service autre que
`set_temperature` sur son entité et revalide son mode juste avant l'envoi. En
défaut il suspend les ordres et conserve les états physiques. La régulation native,
les anti-cycles, l'ECS et la loi d'eau restent à la charge de la PAC. Les têtes
peuvent fermer lorsque les pièces sont satisfaites : le débit indépendant est requis.

La cible normale est conservée sans demande ; la cible réduite s'applique au
blocage Tempo, la cible solaire au surplus qualifié avec une pièce éligible en
demande. Les trois cibles sont des préférences persistantes modifiables en `number`.
La pause et les défauts produisent une cible nulle (aucun ordre, pas une consigne zéro).

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
