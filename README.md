# ![image](https://github.com/user-attachments/assets/c42b3ca3-a681-4091-a13c-f2d0f8f4fc9c) Beem Energy - Intégration Home Assistant ![image](https://github.com/user-attachments/assets/b16dce18-3b0b-4108-9b37-4ebd67372f71)
 
Intégration non officielle permettant de connecter l'ensemble de vos équipements Beem Energy à Home Assistant. 

Suivez votre production solaire, l'état de votre batterie et votre consommation en temps réel.

[![Buy Me a Coffee](https://img.shields.io/badge/buymeacoffee-donate-yellow.svg?logo=buymeacoffee)](https://www.buymeacoffee.com/CharlesP44) [![HACS Validation](https://github.com/CharlesP44/Beem_Energy/actions/workflows/hacs.yml/badge.svg)](https://github.com/CharlesP44/Beem_Energy/actions/workflows/hacs.yml) [![HassFest Validation](https://github.com/CharlesP44/Beem_Energy/actions/workflows/hassfest.yml/badge.svg)](https://github.com/CharlesP44/Beem_Energy/actions/workflows/hassfest.yml)

---
## ✨ Appareils Supportés
Cette intégration a été conçue pour supporter l'écosystème Beem Energy.

✅ Beem Battery : Entièrement supportée, avec récupération des données statiques (état de santé, cycles...) et des flux de puissance en temps réel via MQTT (production solaire, charge/décharge, injection/consommation réseau).

✅ BeemBox / BeemOn (Panneaux Plug & Play) : Entièrement supportée. 

🛠️ Beem EnergySwitch : Partiellement supporté.

---

## 🛠️ Installation
### 1. Via HACS (Méthode Recommandée)
1. Ouvrez HACS dans Home Assistant.
2. Recherchez Beem_Energy et installez-le.
3. Redémarrez Home Assistant.
4. Ajoutez l’intégration via **Paramètres > Appareils et services > Ajouter une intégration** puis cherchez **Beem Energy**.

### 2. Installation Manuelle
1. Téléchargez les fichiers de ce dépôt.
2. Copiez le dossier `beem_integration` dans le répertoire `custom_components/` de votre instance Home Assistant.
3. Redémarrez Home Assistant.
5. Ajoutez l’intégration via **Paramètres > Appareils et services > Ajouter une intégration** puis cherchez **Beem Energy**.

---

## 🔧 Configuration
1. Allez dans Paramètres > Appareils & Services
2. Cliquez sur Ajouter une intégration
3. Recherchez Beem Energy
4. Saisissez 
   - Votre **adresse email** utilisée sur l’application Beem
   - Votre **mot de passe** utilisée sur l’application Beem

L'intégration détectera automatiquement tous vos appareils et créera les entités correspondantes

---

## 📊 Intégration Tableau de bord Energy Home Assistant

Cette intégration est conçue pour fonctionner parfaitement avec le Tableau de Bord Énergie de Home Assistant.

Pour les Panneaux BeemBox
 Le capteur ci dessous peut être utilisés utilisez dans le champ Production Solaire:
  - sensor.<nom_de_votre_beembox>_production_aujourd_hui

Pour la Batterie Beem
Les capteurs d'énergie (en kWh) sont créés automatiquement et peuvent être utilisés comme suit :
 
 - Production Solaire : sensor.batterie_beem_<id>_solarpower_production_kwh
 - Renvoyé au réseau : sensor.batterie_beem_<id>_meterpower_injection_kwh
 - Consommé du réseau : sensor.batterie_beem_<id>_meterpower_consumption_kwh
 - Charge de la batterie : sensor.batterie_beem_<id>_batterypower_charging_kwh
 - Décharge de la batterie : sensor.batterie_beem_<id>_batterypower_discharging_kwh



![image](https://github.com/user-attachments/assets/0d91bd17-646f-4588-8ade-0af72059f9b6)
![1362ead01f59ccd8470af4a6ab31617671ad2d5c](https://github.com/user-attachments/assets/43ae8181-2e1c-4128-81c2-9f9bea19fdfd)

---

## 👨‍💻 Contribution et Support

🧑‍💻 Auteur : @CharlesP44

Cette intégration est un projet personnel. Si vous rencontrez un bug ou avez une suggestion, n'hésitez pas à ouvrir une Issue sur GitHub.

🙏 Remerciements

Merci à la communauté HACF pour les échanges et en particulier à @jrvrcd pour l’aide initiale sur l’authentification.

---

## 📄 Licence

Ce projet est distribué sous la licence MIT. Voir le fichier [LICENSE](LICENSE) pour plus d’informations.

**Il n’est pas affilié officiellement à Beem Energy.**

---
## ☕ Soutien

Si vous appréciez cette intégration et souhaitez soutenir son développement, vous pouvez m'offrir un café !

[![Buy Me a Coffee](https://img.shields.io/badge/buymeacoffee-donate-yellow.svg?logo=buymeacoffee)](https://www.buymeacoffee.com/CharlesP44)

Merci ! 🙏

---


## 📊 Tableau de bord Lovelace (optionnel)

Un tableau de bord Lovelace personnalisé est disponible pour visualiser les données de votre batterie Beem.

### 🧩 Carte Power Flow (requis)

La visualisation utilise la carte personnalisée **Power Flow Card Plus**, disponible via HACS.

### Installation via HACS :

1. Ouvrez HACS > Frontend.
2. Recherchez **Power Flow Card Plus**.
3. Cliquez sur "Installer" puis redémarrez Home Assistant si nécessaire.

> ℹ️ Pour plus d’infos : [Power Flow Card Plus sur GitHub](https://github.com/flixlix/power-flow-card-plus)

### Aperçu

![aperçu lovelace](https://user-images.githubusercontent.com/61006057/227771568-78497ecc-e863-46f2-b29e-e15c7c20a154.gif)

