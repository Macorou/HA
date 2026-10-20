# Essai sans matériel

Le simulateur Python `python tools/simulate.py` exerce le moteur sans Home Assistant,
sans identifiants réseau et sans service physique.

Pour essayer l'interface et les vrais services sur une instance Home Assistant de
test, le package `demo_package.yaml` crée uniquement des helpers et deux thermostats
génériques pilotant des interrupteurs fictifs. Les identifiants ci-dessous sont
ceux **de cette simulation**, pas ceux de l'installation réelle.

1. Activer les packages HA dans la configuration de l'instance de test :

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

2. Copier `demo_package.yaml` dans `config/packages/` puis redémarrer cette instance.
3. Dans Smart Heat Manager, sélectionner le climate « SHM Demo PAC », la sonde
   « SHM Demo Température Salon » et le climate « SHM Demo Tête Salon » comme actionneur.
4. Choisir les helpers Production, Maison, Réseau, PAC électrique, Présence et Tempo.
   Mettre manuellement la PAC fictive en Chauffage : SHM ne l'allume jamais.
5. Modifier les valeurs des helpers depuis l'interface. La température ne change
   pas automatiquement : régler sa valeur permet de simuler un réchauffement.

Le package fournit W et °C, un réseau positif en import et négatif en injection.
Les thermostats génériques simulent les modes natifs LG/tête. Aucun modèle de
compresseur, de débit, de bâtiment ou de cloud LG n'est simulé. Il n'est donc pas
nécessaire de raccourcir les temporisations réelles pour essayer le moteur hors ligne.

Les validations hydraulique/exclusivité/capacités peuvent être cochées uniquement
pour ces équipements fictifs lorsqu'on souhaite tester les services dans cette
instance de laboratoire. Ne pas réutiliser ces confirmations sur l'installation réelle.
