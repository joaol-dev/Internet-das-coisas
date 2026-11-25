# Raiz · Irrigação inteligente

Painel web em português para um irrigador automático com Arduino Uno R3. Mostra umidade do solo, luminosidade, estado da bomba e gráfico das leituras recentes. No histórico, é possível combinar datas, condição do solo, luminosidade mínima e estado da bomba. As datas usam o fuso horário do navegador.

## Executar

Requer Python 3.10+, Docker e Docker Compose. Na raiz do projeto:

```bash
docker compose up -d --wait
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

Abra http://127.0.0.1:8000. No Windows, use `.venv\Scripts\python.exe` no lugar de `.venv/bin/python`. O PostgreSQL 17 local usa um volume persistente. Para utilizar um servidor PostgreSQL existente, defina `DATABASE_URL` e execute o aplicativo com um usuário que possa criar a tabela e o índice.

Por padrão, o aplicativo simula os dois sensores. Em **Simulação de sensores**, aplique uma umidade abaixo de 40% para observar a bomba ligar por 3 segundos e aguardar 5 segundos. Aumente a umidade para 40% ou mais para interromper o ciclo ou use **Pausar**. A interface amostra a simulação a cada segundo. As leituras simuladas e reais são gravadas com origens distintas, e o histórico mostra apenas a origem da sessão atual.

O painel atualiza a leitura ao vivo a cada segundo. O histórico registra a primeira leitura, as mudanças de umidade, luminosidade, bomba ou modo e uma leitura a cada 60 segundos quando os valores ficam estáveis.

## Conectar o Arduino

1. Monte o circuito e carregue [o sketch](firmware/irrigador/irrigador.ino) no Arduino Uno com a biblioteca Arduino LiquidCrystal.
2. Ajuste `SOIL_DRY` e `SOIL_WET` com os valores brutos do sensor nas referências seca e úmida. Os valores iniciais, 0 e 876, vêm do sketch do Tinkercad. A leitura de luminosidade corresponde à escala do conversor analógico, em porcentagem e sem conversão para lux. Os dois sensores acompanham o mesmo canteiro. O LDR fornece contexto sobre a exposição à luz e a umidade controla a bomba.
3. Feche o Monitor Serial e rode `.venv/bin/python app.py --serial /dev/ttyACM0` no computador conectado ao Arduino. Substitua pela porta correta, por exemplo `COM3` no Windows.

| Componente | Ligação no Uno |
| --- | --- |
| Sensor de umidade analógico | Saída em A0, alimentação conforme o módulo e GND comum |
| LDR e resistor adicional de 10 kΩ | LDR entre 5 V e A1, resistor fixo entre A1 e GND |
| LCD 16 × 2 paralelo | RS em D12, E em D11, DB4–DB7 em D5, D4, D3 e D2, R/W e VSS em GND, VDD em 5 V |
| Contraste do LCD | Extremos do potenciômetro de 10 kΩ em 5 V e GND, cursor em VO |
| Backlight | A em 5 V através de 220 Ω, K em GND |
| LEDs verde, vermelho e amarelo | D8, D9 e D10 respectivamente, cada LED com 220 Ω em série. Verde indica umidade de 40% ou mais, vermelho indica solo seco e amarelo indica bomba ligada. |
| Relé de bobina de 5 V | D7 à base do NPN através de 1 kΩ. Emissor em GND, coletor na bobina e outro terminal da bobina em 5 V |
| Diodo 1N4007 | Em paralelo com a bobina, cátodo no lado de 5 V |
| Motor e bateria de 6 V | Positivo da bateria em COM, NO no positivo do motor, negativo do motor no negativo da bateria. Use um polo de um relé DPDT se aplicável |

Dimensione o transistor e a alimentação de 5 V para a corrente da bobina, e os contatos do relé para a corrente do motor. Para o LCD com numeração de 1 a 16, use DB4–DB7 nos pinos físicos 11–14.

A serial opera a 9600 baud. O sketch envia `DATA,umidade,luz,bomba,modo` com fim de linha, e recebe `AUTO` ou `PAUSE`. A interface confirma o comando com o modo informado em uma leitura subsequente. O firmware calcula a temporização com `millis()` e continua funcionando durante uma desconexão serial. O estado da bomba representa o acionamento do relé. O LCD mostra umidade e estado do motor.

O servidor escuta apenas no endereço local por padrão. Use o modo de simulação para demonstrações em rede.
