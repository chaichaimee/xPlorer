<p align="center">
  <img src="https://www.nvaccess.org/files/nvda/documentation/userGuide/images/nvda.ico" alt="NVDA Logo" width="120">
</p>

# <p align="center">xPlorer</p>

<br>

<p align="center">Mejore su experiencia en el Explorador de archivos con automatización avanzada y herramientas de navegación fluidas.</p>

<br>

<p align="center"><b>autor:</b> chai chaimee</p>
<p align="center"><b>url:</b> https://github.com/chaichaimee/xPlorer</p>

---

## <p align="center">Descripción</p>

**xPlorer** es una suite de productividad integral para usuarios de NVDA, diseñada específicamente para que el Explorador de archivos de Windows sea más inteligente y eficiente. Elimina las dificultades de la gestión de archivos diaria mediante la automatización de tareas repetitivas y la optimización de la navegación. Ya sea que esté creando estructuras de carpetas por lotes, estandarizando nombres con conversión de mayúsculas profesional o extrayendo texto de archivos sin abrirlos, xPlorer ofrece una experiencia fluida de nivel desarrollador para cada usuario. Se trata de hacer más con menos pulsaciones de teclas.

<br>

## <p align="center">Novedades</p>

• **Crear múltiples carpetas:** Genere instantáneamente una estructura de directorios completa a partir de una sola lista.  
<br>
• **Conversor de mayúsculas para carpetas:** Estandarice los nombres de las carpetas con opciones profesionales (MAYÚSCULAS, minúsculas, Tipo Título, Tipo Oración).  
<br>
• **Información detallada de la carpeta:** Obtenga el tamaño y el recuento de elementos de las carpetas en tiempo real directamente desde el menú.  
<br>
• **Optimización de títulos:** Suprima el redundante "- Explorador de archivos" en los títulos de las ventanas para una salida de voz más limpia.  
<br>
• **Creación instantánea de carpetas:** Use automáticamente el contenido del portapapeles como nombre al crear una nueva carpeta.

<br>

## <p align="center">Teclas rápidas</p>

> **NVDA+Shift+X** : Abrir el menú contextual de xPlorer  
> (El centro maestro para todas las funciones profesionales, incluyendo el conversor de mayúsculas y el creador de múltiples carpetas)

> **NVDA+Shift+Z** > • **Un toque** : Decir tamaño (Anuncia el tamaño total de los elementos seleccionados)  
> • **Dos toques** : Comprimir en Zip (Archiva los archivos seleccionados en un .zip con nombres inteligentes)

> **NVDA+Shift+C** > • **Un toque** : Copiar nombres seleccionados (Copia los nombres de los archivos o carpetas seleccionados al portapapeles)  
> • **Dos toques** : Copiar ruta de la carpeta actual (Obtiene la ruta completa de la carpeta actual)

> **NVDA+Shift+V** > • **Un toque** : Copiar contenido (Extrae y copia el contenido de texto directamente del archivo seleccionado)  
> • **Dos toques** : Invertir selección (Cambia rápidamente el foco entre elementos seleccionados y no seleccionados)

> **NVDA+Shift+F2** : Renombrar solo archivo  
> (Se enfoca solo en el nombre del archivo, protegiendo la extensión de cambios accidentales)

> **Control+Shift+N** : Crear nueva carpeta con pegado automático  
> (Crea una nueva carpeta y pega instantáneamente el contenido del portapapeles como su nombre)

<br>

## <p align="center">Características</p>

### <p align="center">1. Creación avanzada de carpetas por lotes</p>

La función **"Crear múltiples carpetas"** (que se encuentra en el menú xPlorer) está diseñada para una organización seria. En lugar de crear carpetas una por una, puede pegar o escribir una lista de nombres en un solo cuadro de diálogo. xPlorer procesará la lista completa y creará cada carpeta en su directorio actual en un abrir y cerrar de ojos. Es el máximo ahorro de tiempo para configurar nuevos proyectos o categorías.

### <p align="center">2. Conversor de mayúsculas profesional</p>

Asegúrese de que su sistema de archivos se vea limpio y coherente. Seleccione cualquier carpeta(s) y use el menú xPlorer para convertir nombres al instante:  
<br>
• **MAYÚSCULAS:** Convierte todo a letras mayúsculas (ej., "DATOS DEL PROYECTO").  
<br>
• **minúsculas:** Convierte todo a letras minúsculas (ej., "datos del proyecto").  
<br>
• **Tipo Título:** Pone en mayúscula la primera letra de cada palabra (ej., "Datos Del Proyecto").  
<br>
• **Tipo Oración:** Solo se pone en mayúscula la primera letra (ej., "Datos del proyecto").

### <p align="center">3. Creación inteligente de "Portapapeles a carpeta"</p>

Con xPlorer, crear carpetas se convierte en un proceso de un solo paso. Al presionar **Control+Shift+N**, el complemento verifica su portapapeles. Si tiene un nombre copiado de un correo electrónico o documento, crea la carpeta y pega automáticamente ese nombre en el campo de edición. No más cambios de nombre o pegados manuales: solo copie, presione la tecla rápida y listo.

### <p align="center">4. Extracción de contenido de archivos</p>

Ahorre tiempo extrayendo texto sin abrir aplicaciones. **Un toque NVDA+Shift+V** para extraer el texto de un archivo seleccionado directamente a su portapapeles. Esto funciona sin esfuerzo con varios formatos basados en texto, lo que le permite obtener datos de scripts o registros mientras se mantiene enfocado en la ventana del Explorador.

### <p align="center">5. Archivado Zip inteligente</p>

Al pulsar **dos veces NVDA+Shift+Z**, xPlorer empaqueta su selección en un archivo zip. Evita inteligentemente la pérdida de datos al verificar archivos existentes y agregar un sufijo numérico a los nuevos archivos. Los tonos de audio de fondo le mantienen informado del progreso de la compresión sin necesidad de supervisión visual.

### <p align="center">6. Panel de configuración de xPlorer</p>

Personalice su experiencia a través de **Configuración de NVDA > xPlorer**. Las opciones están dispuestas para optimizar su flujo de trabajo:  
<br>
<br>
• **Seleccionar automáticamente el primer elemento:** Al entrar en una carpeta, xPlorer pondrá automáticamente el foco en el primer archivo o carpeta para que pueda empezar a navegar de inmediato.  
<br>
• **Anunciar 'Carpeta vacía' al entrar en una carpeta vacía:** Proporciona una confirmación vocal clara de que un directorio no contiene elementos.  
<br>
• **Suprimir el anuncio de la clase DirectUIHWND:** Elimina el desorden técnico del habla de NVDA, proporcionando una interfaz de audio más limpia.  
<br>
• **Suprimir el anuncio de '- Explorador de archivos' en los títulos de las ventanas:** Acorta los anuncios de los títulos de las ventanas, ayudándole a identificar las carpetas más rápido.  
<br>
• **Pegar automáticamente el contenido del portapapeles en el campo de cambio de nombre:** Permite a xPlorer completar automáticamente los nombres desde su portapapeles para una máxima eficiencia al crear nuevas carpetas.

<br>

---

<br>
<br>

## <p align="center">Apóyame</p>

<p align="center">Si esta herramienta le ha facilitado la vida, considere impulsar la próxima actualización con una pequeña donación.</p>

<br>

<p align="center">
  <a href="https://buy.stripe.com/dRm9AU1xQ3Ds22N6VK1VK01">
    <img src="https://img.shields.io/badge/Donate-Support%20Me-blue?style=for-the-badge&logo=stripe" alt="Support me">
  </a>
</p>

<br>

<p align="center">Su apoyo significa mucho. ¡Construyamos algo grandioso juntos!</p>

<br>

<p align="center">© 2026 Chai Chaimee NVDA Add-on Lanzado bajo GNU GPL</p>