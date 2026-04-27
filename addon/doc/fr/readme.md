<p align="center">
  <img src="https://www.nvaccess.org/files/nvda/documentation/userGuide/images/nvda.ico" alt="NVDA Logo" width="120">
</p>

# <p align="center">xPlorer</p>

<br>

<p align="center">Améliorez votre expérience de l'Explorateur de fichiers avec une automatisation avancée et des outils de navigation fluides.</p>

<br>

<p align="center"><b>auteur :</b> chai chaimee</p>
<p align="center"><b>url :</b> https://github.com/chaichaimee/xPlorer</p>

---

## <p align="center">Description</p>

**xPlorer** est une suite de productivité complète pour les utilisateurs de NVDA, spécifiquement conçue pour rendre l'Explorateur de fichiers Windows plus intelligent et plus efficace. Il élimine les frictions de la gestion quotidienne des fichiers en automatisant les tâches répétitives et en simplifiant la navigation. Que vous créiez des structures de dossiers par lots, normalisiez les noms avec une conversion de casse professionnelle ou extrayiez du texte de fichiers sans les ouvrir, xPlorer offre une expérience fluide de niveau développeur pour chaque utilisateur. Il s'agit d'en faire plus avec moins de touches.

<br>

## <p align="center">Quoi de neuf</p>

• **Créer plusieurs dossiers :** Gérez instantanément toute une structure de répertoires à partir d'une seule liste.  
<br>
• **Convertisseur de casse pour les dossiers :** Normalisez les noms de dossiers avec des options de casse professionnelles (MAJUSCULES, minuscules, Casse de Titre, Casse de Phrase).  
<br>
• **Infos détaillées sur les dossiers :** Obtenez la taille et le nombre d'éléments en temps réel directement depuis le menu.  
<br>
• **Optimisation des titres :** Supprimez le redondant "- Explorateur de fichiers" dans les titres de fenêtres pour une sortie vocale plus claire.  
<br>
• **Création instantanée de dossiers :** Utilisez automatiquement le contenu du presse-papiers comme nom lors de la création d'un nouveau dossier.

<br>

## <p align="center">Raccourcis Clavier</p>

> **NVDA+Maj+X** : Ouvrir le menu contextuel xPlorer  
> (Le hub principal pour toutes les fonctionnalités professionnelles, y compris le convertisseur de casse et le créateur multi-dossiers)

> **NVDA+Maj+Z** > • **Appui simple** : Dire la taille (Annonce la taille totale des éléments sélectionnés)  
> • **Appui double** : Compresser en Zip (Archive les fichiers sélectionnés dans un .zip avec un nommage intelligent)

> **NVDA+Maj+C** > • **Appui simple** : Copier les noms sélectionnés (Copie les noms des fichiers ou dossiers sélectionnés dans le presse-papiers)  
> • **Appui double** : Copier le chemin du dossier actuel (Récupère le chemin complet du dossier courant)

> **NVDA+Maj+V** > • **Appui simple** : Copier le contenu (Extrait et copie le contenu textuel directement du fichier sélectionné)  
> • **Appui double** : Inverser la sélection (Bascule rapidement le focus entre les éléments sélectionnés et non sélectionnés)

> **NVDA+Maj+F2** : Renommer le fichier uniquement  
> (Se concentre uniquement sur le nom du fichier, protégeant l'extension contre les modifications accidentelles)

> **Control+Maj+N** : Créer un nouveau dossier avec collage auto  
> (Crée un nouveau dossier et colle instantanément le contenu de votre presse-papiers comme nom)

<br>

## <p align="center">Fonctionnalités</p>

### <p align="center">1. Création avancée de dossiers par lots</p>

La fonctionnalité **"Créer plusieurs dossiers"** (dans le menu xPlorer) est conçue pour une organisation sérieuse. Au lieu de créer les dossiers un par un, vous pouvez coller ou taper une liste de noms dans une seule boîte de dialogue. xPlorer traitera toute la liste et créera chaque dossier dans votre répertoire actuel en un instant. C'est le gain de temps ultime pour configurer de nouveaux projets.

### <p align="center">2. Convertisseur de casse professionnel</p>

Assurez-vous que votre système de fichiers est propre et cohérent. Sélectionnez un ou plusieurs dossiers et utilisez le menu xPlorer pour convertir les noms instantanément :  
<br>
• **MAJUSCULES :** Convertit tout en lettres capitales (ex: "DONNÉES PROJET").  
<br>
• **minuscules :** Convertit tout en petites lettres (ex: "données projet").  
<br>
• **Casse de Titre :** Met une majuscule à la première lettre de chaque mot (ex: "Données Projet").  
<br>
• **Casse de Phrase :** Seule la toute première lettre est en majuscule (ex: "Données projet").

### <p align="center">3. Création intelligente "Presse-papiers vers dossier"</p>

Avec xPlorer, la création de dossiers devient un processus en une seule étape. En appuyant sur **Control+Maj+N**, l'extension vérifie votre presse-papiers. Si vous avez un nom copié, elle crée le dossier et colle automatiquement ce nom. Plus de renommage manuel—copiez, appuyez sur le raccourci, et c'est fait.

### <p align="center">4. Extraction du contenu des fichiers</p>

Gagnez du temps en extrayant du texte sans ouvrir d'applications. **Appui simple NVDA+Maj+V** pour extraire le texte d'un fichier sélectionné directement dans votre presse-papiers. Cela fonctionne avec divers formats texte, vous permettant de récupérer des données tout en restant dans l'Explorateur.

### <p align="center">5. Archivage Zip intelligent</p>

En **appuyant deux fois sur NVDA+Maj+Z**, xPlorer emballe votre sélection dans un fichier zip. Il évite intelligemment la perte de données en vérifiant les fichiers existants et en ajoutant un suffixe numérique. Des sons en arrière-plan vous informent de la progression.

### <p align="center">6. Panneau de réglages xPlorer</p>

Personnalisez votre expérience via **Paramètres NVDA > xPlorer** :  
<br>
<br>
• **Sélectionner automatiquement le premier élément :** En entrant dans un dossier, le focus est mis sur le premier fichier.  
<br>
• **Annoncer 'Dossier vide' :** Confirmation vocale claire qu'un répertoire ne contient rien.  
<br>
• **Supprimer l'annonce de la classe DirectUIHWND :** Élimine l'encombrement technique de la parole NVDA.  
<br>
• **Supprimer '- Explorateur de fichiers' des titres :** Raccourcit les annonces de titres pour identifier les dossiers plus vite.  
<br>
• **Coller automatiquement le presse-papiers lors du renommage :** Pour une efficacité maximale lors de la création de dossiers.

<br>

---

<br>
<br>

## <p align="center">Soutenez-moi</p>

<p align="center">Si cet outil vous a facilité la vie, envisagez de soutenir la prochaine mise à jour avec un petit don.</p>

<br>

<p align="center">
  <a href="https://buy.stripe.com/dRm9AU1xQ3Ds22N6VK1VK01">
    <img src="https://img.shields.io/badge/Donate-Support%20Me-blue?style=for-the-badge&logo=stripe" alt="Support me">
  </a>
</p>

<br>

<p align="center">Votre soutien compte énormément. Construisons de grandes choses ensemble !</p>

<br>

<p align="center">© 2026 Chai Chaimee NVDA Add-on Publié sous GNU GPL</p>