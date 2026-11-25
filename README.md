# Raiz · Irrigação inteligente

Painel web em português para um irrigador automático com Arduino Uno R3. Mostra umidade do solo, luminosidade, estado da bomba e gráfico das leituras recentes. No histórico, é possível combinar datas, condição do solo, luminosidade mínima e estado da bomba. As datas usam o fuso horário do navegador.

## Executar com o Neon

O painel usa Python 3.10+ e um banco PostgreSQL no Neon. No painel do Neon, abra seu projeto, clique em **Connect** e selecione a branch, o banco e a role. Copie a URL de conexão completa, incluindo os parâmetros TLS fornecidos pelo Neon. Use uma role com permissão para criar a tabela e o índice na primeira inicialização.

### Windows (Prompt de Comando)

Na pasta do projeto, substitua o exemplo de `DATABASE_URL` pela URL copiada e rode:

```bat
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
set "DATABASE_URL=COLE_A_URL_COMPLETA_DO_NEON_AQUI"
.venv\Scripts\python.exe app.py
```

### Linux e macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export DATABASE_URL='COLE_A_URL_COMPLETA_DO_NEON_AQUI'
.venv/bin/python app.py
```

Acesse http://127.0.0.1:8000. Mantenha o terminal aberto enquanto usa o painel. Ao abrir outro terminal, defina `DATABASE_URL` novamente antes de executar o aplicativo. A URL contém a senha do banco e deve ficar fora dos arquivos versionados.

Por padrão, o aplicativo simula os dois sensores. Em **Simulação de sensores**, aplique uma umidade abaixo de 40% para observar a bomba ligar por 3 segundos e aguardar 5 segundos. Aumente a umidade para 40% ou mais para interromper o ciclo ou use **Pausar**. A interface amostra a simulação a cada segundo. As leituras simuladas e reais são gravadas com origens distintas, e o histórico mostra apenas a origem da sessão atual.

O painel atualiza a leitura ao vivo a cada segundo. O histórico registra a primeira leitura, as mudanças de umidade, luminosidade, bomba ou modo e uma leitura a cada 60 segundos quando os valores ficam estáveis.

## Conectar o Arduino

1. Monte o circuito e carregue [o sketch](firmware/irrigador/irrigador.ino) no Arduino Uno com a biblioteca Arduino LiquidCrystal.
2. Ajuste `SOIL_DRY` e `SOIL_WET` com os valores brutos do sensor nas referências seca e úmida. Os valores iniciais, 0 e 876, vêm do sketch do Tinkercad. A leitura de luminosidade corresponde à escala do conversor analógico, em porcentagem e sem conversão para lux. Os dois sensores acompanham o mesmo canteiro. O LDR fornece contexto sobre a exposição à luz e a umidade controla a bomba.
3. Feche o Monitor Serial. No computador conectado ao Arduino, configure `DATABASE_URL` como descrito acima e rode `.venv\Scripts\python.exe app.py --serial COM3` no Windows ou `.venv/bin/python app.py --serial /dev/ttyACM0` no Linux. Substitua a porta pela usada na sua máquina.

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
