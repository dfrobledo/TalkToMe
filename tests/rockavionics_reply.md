Contexto que ya existe
- La arquitectura está decidida desde el 14-09: un módem tonto en la segunda XIAO. El FC le manda el flujo por UART (D0/D1, GPIO1/2, que siguen libres en config_fc.h; Serial2 ya lo usa el GPS). El módem reenvía por LoRa P2P crudo en 915 MHz solo TELEMETRÍA y EVENTO, y en tierra recibe el HAT SX1262 del Pi desde Python.
- Falta todo: Tipo::TELEMETRIA = 8 está reservado pero no tiene carga, no hay código del UART al módem, el módem no tiene firmware y no hay receptor.

Decidido, con su derivación
- Meshtastic queda descartado. Su preset LongFast (SF11/BW250) necesita cerca de 1 s de aire por paquete, así que no llega a los 10 Hz que pide la spec.
- Cuánto aire ocupa cada trama de 38 B (32 de carga más 6 de marco), con SF7:

| Ancho de banda | Aire por trama | Ocupación a 10 Hz |
|----------------|----------------|-------------------|
| 125 kHz        | 82 ms          | 82 %              |

- Con 500 kHz sobra margen.

Pregunta: para el spike hacen falta dos radios. ¿El Pi 5 con el HAT SX1262 ya está operativo (arranca y le llego por SSH desde este PC)?
- Sí: el spike es un enlace real Wio → HAT con aire y RSSI medidos.
- No: el spike se queda en una sola radio.

Qué necesito de ti: la respuesta sobre el Pi.
