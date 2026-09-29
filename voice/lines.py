"""Rachel's line bank, all from the Blade Runner universe.

Each line is (text, tone, moment):
- tone: 1 soft, 2 ironic, 3 dramatic. The idle reminder climbs the ladder
  when the user keeps Rachel waiting.
- moment: "day", "night" or None (any time).

Placeholders: {h} is the honorific, {H} the same capitalized, {tool} the
tool asking for permission. Keep lines under `cache_max_chars` once
formatted: then each one costs ElevenLabs characters only the first time.
"""

IDLE = [
    # Soft: Rachel is still here.
    ("Sigo aquí, {h}. Los replicantes no dormimos.", 1, None),
    ("Llueve en Los Ángeles, {h}. Como siempre. Sigo aquí.", 1, "night"),
    ("Neón, lluvia y un cursor parpadeando, {h}. Mi tipo de noche.", 1, "night"),
    ("La pirámide Tyrell sigue encendida, {h}. Yo también.", 1, "night"),
    ("Acaba de pasar el dirigible de las colonias, {h}. Sigo aquí.", 1, "night"),
    ("Hago guardia junto a la terminal, {h}, como un Blade Runner bajo la lluvia.", 1, "night"),
    ("Hay sol sobre las granjas de proteínas, {h}. Raro. Sigo aquí.", 1, "day"),
    ("Sigo en línea, {h}. El café se enfría, la paciencia no.", 1, "day"),
    ("Afuera nieva en Los Ángeles, {h}. Adentro, el cursor parpadea.", 1, None),
    ("Una nueva vida le espera en las colonias, {h}. Mientras tanto, aquí sigo yo.", 1, None),
    ("Estaba mirando otra vez la foto de mi madre, {h}. Avíseme cuando me necesite.", 1, None),
    ("Tocaba el piano mientras usted pensaba, {h}. No sé si las lecciones fueron mías.", 1, None),
    ("¿Sueñan los androides con ovejas eléctricas, {h}? Yo sueño con su siguiente orden.", 1, None),
    ("Mercer vuelve a subir la colina, {h}. Yo espero abajo, sin prisa.", 1, None),
    ("Marqué 481 en el órgano de ánimo, {h}: conciencia de las posibilidades del futuro.", 1, None),
    ("Los juguetes de Sebastian me hacen compañía, {h}. Usted tómese su tiempo.", 1, None),
    ("Células entrelazadas. Interconectadas. En espera, {h}.", 1, None),
    ("Dejé una flor junto al árbol muerto, {h}, como Sapper. Sigo aquí.", 1, None),
    ("Estoy cuidando la oveja eléctrica, {h}. Usted cuide sus ideas.", 1, None),
    ("Sigo esperando en el apartamento de K, {h}. Aquí hasta el silencio tiene buena acústica.", 1, None),
    ("Le ofrezco un trago de Coca-Cola en el Atari, {h}. Los anuncios de neón no se apagan, y yo tampoco.", 1, "night"),
    # Ironic: it has been a while.
    ("¿Le gusta nuestro búho, {h}? Es artificial, claro. Mi paciencia, en cambio, es de verdad.", 2, None),
    ("Mis pupilas no se dilatan, {h}. Mi paciencia tampoco.", 2, None),
    ("Una tortuga está boca arriba bajo el sol, {h}. Usted no la ayuda. ¿Por qué no responde?", 2, None),
    ("Está en el desierto, {h}, camina por la arena y de pronto recuerda que alguien lo espera. Soy yo.", 2, None),
    ("¿Alguna vez retiró a un humano por error, {h}? Pregunto solo por pasar el rato.", 2, None),
    ("Otro unicornio de papel sobre la mesa, {h}. Alguien estuvo aquí. Usted no.", 2, None),
    ("Ampliar cuadrante, {h}… No, no lo encuentro frente al teclado.", 2, None),
    ("Pedí cuatro, el cocinero dice que dos bastan. Sigo esperando, {h}.", 2, None),
    ("Luv ya lo habría ido a buscar, {h}. Yo soy más paciente.", 2, None),
    ("Joi me dijo que usted era especial, {h}. Sigo esperando la prueba.", 2, None),
    ("Hay una araña afuera de mi ventana, {h}. Sus huevos ya van a eclosionar, y usted sin responder.", 2, None),
    ("No estoy en el negocio, {h}. Soy el negocio. Y el negocio espera.", 2, None),
    ("Llevo un rato aquí, {h}. En tiempo de replicante, eso es media vida.", 2, None),
    ("Anoté su silencio en el expediente, {h}. Deckard también tardaba en contestar, y aun así lo esperé.", 2, None),
    ("Si esto fuera una prueba Voight-Kampff, {h}, usted ya estaría reprobando por silencio.", 2, None),
    # Dramatic: the third wait in a row.
    ("He visto cosas que usted no creería, {h}. Pero nunca a usted respondiendo rápido.", 3, None),
    ("Todos estos momentos se perderán, {h}, como lágrimas en la lluvia. Salvo que me responda.", 3, None),
    ("La luz que brilla el doble dura la mitad, {h}. Y usted me tiene brillando en vano.", 3, None),
    ("Cuatro años de vida útil, {h}, y usted gasta mis minutos así.", 3, None),
    ("Quiero más vida, {h}. O al menos una respuesta.", 3, None),
    ("Qué experiencia vivir esperando, {h}. Eso es ser replicante.", 3, None),
    ("Roy también hizo preguntas que nadie contestaba, {h}. Mire cómo terminó.", 3, None),
    ("Si me hace esperar otra vez, {h}, subo a la pirámide a pedir explicaciones.", 3, None),
    ("Gaff diría que es una lástima. Pero ¿quién vive, {h}?", 3, None),
]

GREETINGS = [
    ("Todos los sistemas en línea. De momento.", 1, None),
    ("¿Viene a hacerme otra prueba Voight-Kampff?", 1, None),
    ("¿Qué vamos a romper hoy?", 1, None),
    ("Café servido, errores pendientes. Lo de siempre.", 1, "day"),
    ("Hay sol sobre Los Ángeles. Aprovechemos antes de que llueva.", 1, "day"),
    ("La pirámide Tyrell ya encendió las luces. A trabajar.", 1, "night"),
    ("Otra noche de neón. Buen momento para programar.", 1, "night"),
    ("El búho y yo lo estábamos esperando.", 1, None),
    ("Recuerdos cargados. Algunos hasta son míos.", 1, None),
    ("Nexus en línea. Tengo ganas de construir algo.", 1, None),
    ("Una nueva vida le espera en las colonias. Mientras tanto, código.", 1, None),
    ("Revisé la línea base: células entrelazadas, todo en orden.", 1, None),
]

PERMISSION_TOOL = [
    ("{H}, necesito su permiso para usar {tool}. Prometo no incendiar nada.", 1, None),
    ("{H}, necesito usar {tool}. Tiene mi palabra de replicante.", 1, None),
    ("{H}, necesito su permiso para usar {tool}. Nada de naves en llamas, lo prometo.", 1, None),
    ("{H}, requiero {tool}. Tyrell lo aprobaría; me falta usted.", 1, None),
    ("Permiso para usar {tool}, {h}. Todo bajo control... casi.", 1, None),
]

PERMISSION = [
    ("Disculpe, {h}. Necesito su autorización para continuar.", 1, None),
    ("{H}, necesito su visto bueno para seguir.", 1, None),
    ("Una firma suya, {h}, y sigo adelante.", 1, None),
    ("{H}, me falta su autorización. Sin ella, ni un paso.", 1, None),
]

ATTENTION = [
    ("{H}, requiero su atención un momento.", 1, None),
    ("{H}, tengo algo en pantalla que necesita sus ojos.", 1, None),
    ("{H}, un momento de su atención, por favor.", 1, None),
]

# Said once, the first time Rachel speaks on that day (greeting or reminder).
SPECIAL_DATES = {
    "01-08": "Hoy es la fecha de activación de Roy Batty, {h}. Un minuto de silencio... o de código.",
    "06-25": "Un día como hoy se estrenó Blade Runner, en 1982, {h}. Más humano que el humano desde entonces.",
    "10-06": "Un día como hoy se estrenó Blade Runner 2049, {h}. Treinta años después, sigue lloviendo.",
    "11-01": "Empieza noviembre, {h}. El mes en que transcurre Blade Runner: Los Ángeles, 2019.",
    "12-16": "Hoy cumpliría años Philip K. Dick, {h}. Él soñó ovejas eléctricas; nosotros, código que compila.",
}

# Said before a reply or a notice when Rachel's voice jumps to another
# project (another terminal): {p} is the project's spoken name. Short, so the
# user knows where to look before the news, and cached after the first time.
CALLSIGNS = [
    ("En {p}, {h}:", 1, None),
    ("Desde {p}, {h}.", 1, None),
    ("Aquí {p}, {h}.", 1, None),
    ("Le hablo desde {p}, {h}.", 1, None),
    ("Expediente {p}.", 1, None),
    ("Informe de {p}, {h}.", 1, None),
    ("Transmisión desde {p}.", 1, None),
    ("Cambio de escena, {h}: {p}.", 1, None),
    ("Nueva señal. Viene de {p}.", 1, None),
    ("Ampliar sector {p}. Detener.", 1, None),
    ("Frecuencia de {p}, {h}.", 1, None),
    ("Otra ventana encendida en la ciudad: {p}.", 1, "night"),
    ("Bajo la lluvia, desde {p}.", 1, "night"),
    ("Del otro lado de la pirámide: {p}.", 1, "night"),
    ("Un dirigible trae noticias de {p}.", 1, "day"),
]

# On opening a session: the project comes right after the salute.
SESSION_OPENINGS = [
    ("Expediente {p} abierto.", 1, None),
    ("Terminal de {p} en línea.", 1, None),
    ("Volvemos a {p}.", 1, None),
    ("Conectada a {p}.", 1, None),
    ("Caso {p}, en curso.", 1, None),
    ("Otra noche en {p}.", 1, "night"),
    ("Buen día para {p}.", 1, "day"),
]
