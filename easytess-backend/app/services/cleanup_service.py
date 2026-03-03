import os
import shutil
import logging
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

def empty_temp_folder(folder_path):
    """
    Vide complètement le dossier temporaire.
    """
    logger.info(f"Démarrage du nettoyage automatique du dossier : {folder_path}")
    if not os.path.exists(folder_path):
        logger.warning(f"Le dossier {folder_path} n'existe pas.")
        return

    deleted_count = 0
    try:
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                    deleted_count += 1
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                    deleted_count += 1
            except Exception as e:
                logger.error(f"Erreur lors de la suppression de {file_path}. Raison: {e}")
        logger.info(f"Nettoyage de {folder_path} terminé. {deleted_count} éléments supprimés.")
    except Exception as e:
        logger.error(f"Erreur lors de l'accès au dossier {folder_path} : {e}")

def init_cleanup_scheduler(app):
    """
    Initialise le planificateur de tâches en arrière-plan (APScheduler) pour vider le dossier temporaire.
    """
    temp_folder = app.config.get('UPLOAD_TEMP_FOLDER')
    if not temp_folder:
        logger.error("UPLOAD_TEMP_FOLDER non défini dans la configuration de l'application.")
        return

    scheduler = BackgroundScheduler()
    
    # Planifie l'exécution de cette tâche toutes les 48 heures (trigger='interval', hours=48)
    scheduler.add_job(
        func=empty_temp_folder,
        trigger="interval",
        hours=48,
        args=[temp_folder],
        id='empty_temp_folder_job',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info(f"Scheduler configuré pour vider {temp_folder} toutes les 48h.")
