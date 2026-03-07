# Транскрипція: Home Assistant - integration and working with Deye inverters, part 1

**Відео:** https://www.youtube.com/watch?v=QbwqaIBkb3A  
**Канал:** Alex Kvazis - технологии умного дома  
**Тривалість:** 18:50  
**Опубліковано:** 4 березня 2026

## Розділи (Chapters)

- 00:00 Introduction
- 01:13 Installation
- 05:26 Integration
- 10:37 Logic
- 17:31 Announcement of the second part

---

## Повна транскрипція (англійською)

Hello friends. In this video I want to share with you my new experience - integrating a Deye inverter into Home Assistant, which I finally decided to install. The point is to extend the broad capabilities of Home Assistant to the home backup power system as well, getting not just monitoring, but a full-fledged tool for controlling the backup power system.

Actually, the main part of this video - is dedicated specifically to the logic, since the integration process itself is very simple and fast, requiring no special knowledge. I decided that within one video - describing all the logic I have created so far - would be very cumbersome, so I decided to split it into two parts. In the second part - different battery operating modes will be shown, which make it possible to shift its charging time to the night tariff. I would be glad - if you share your experience and developments in the comments to this video.

Before we begin, as usual, I ask you to like this video so that more people who are interested in the smart home topic can find it, and subscribe to my channel if you haven't done so before.

When I finally matured to switching to a centralized backup power system for the entire apartment, it was the smart home system that gave me the most valuable information — real energy consumption statistics. I saw not only the current power, but also peak values, the average load per day, distribution by phases, and the behavior of the system in different periods of time. And this made it possible to make a decision not "by eye," but based on actual data.

Initially, I decided to focus on an option whose power would be sufficient to supply all consumers without the need to introduce restrictions or manually disconnect some lines. But the approach can be different: some people back up only critical loads — lighting, refrigerator, router, boiler. Others — the entire apartment as a whole. This is already a question of budget, priorities, and the desired level of comfort.

After I decided on the desired inverter power, the next important stage is choosing a battery. And here it is important to consider not only the capacity in kilowatt-hours, but also the maximum discharge current that the battery BMS allows. For example, if the inverter is rated for 8 kW, then with a 48 V system this is already on the order of 160 amps of current. And not every battery is capable of operating for a long time in such a mode without limitations. Therefore, the battery must match the inverter not only in voltage, but also in allowable discharge power, and ideally — have a margin for this parameter.

In addition, you need to understand in advance what autonomy you want to get — one hour, three hours, or half a day. The required capacity of the storage system will depend on this.

It is also necessary to consider separately the situation when the city grid returns after an outage. At this moment, the inverter not only starts powering the apartment again, but also simultaneously starts charging the battery. Which means the total power consumed from the grid can increase significantly. If you do not take this into account, you can get an overload on the main input circuit breaker. For example, if you have a 25 or 32 amp breaker, and the inverter begins actively charging the battery at full power, the total current may exceed the permissible value. Fortunately, in Deye inverters you can limit the input power and charging current. But you need to understand that reducing the charging current increases the full battery charging time — and this is always a compromise between recovery speed and a safe load on the input.

Having all this information on the load and the required autonomy, I began searching for a solution of the appropriate power with turnkey installation.

The placement location was chosen to be the wall where the electrical panel is located. In my case, this was the only technically possible option — all wiring is already concentrated in this place, which means the lengths of the power cables and the rework of the existing scheme are minimized.

Since my apartment has a three-phase input, a three-phase hybrid inverter was the logical choice. With a three-phase input, using a single-phase inverter means either backing up only one phase, or the need for a serious rework of load distribution. In addition, there is a risk of phase imbalance. A three-phase inverter allows you to keep the existing apartment power supply scheme and work correctly with all lines without redistributing loads.

As a result, the following configuration was obtained: a three-phase hybrid inverter, a corresponding battery, a separate distribution box with breakers for the inverter input and output, as well as a three-position load switch — inverter, city grid, or off. Such a switch allows you to manually select the power source in case of system maintenance or an unusual situation.

In normal mode, the apartment is powered through the inverter in grid pass-through mode — when the city grid is available it works as a bypass, and when it disappears it automatically switches to battery power.

The specific power of the equipment in the context of this video is not critical, since the integration and automation logic remains the same for the entire line of Deye inverters.

**For initial setup, the inverter must be connected to the official Deye Cloud application.** This means connecting the device to your Wi-Fi network and registering it in the manufacturer's cloud. And here I want to give an important piece of advice — be sure to require that the installers perform the connection immediately to your account. Sometimes you can hear: "I'll connect it to mine, and then I'll transfer access — it's faster." But in this case we are talking about the power supply system of your home, and full control over it should be only with you.

Personally, I use the official app mainly for monitoring. You need to keep in mind that the data here is updated with a delay — as a rule, once every few minutes. All the main control and automation logic is implemented already through Home Assistant, which is what I will talk about next.

**After the inverter was connected to my home network, I installed the Solarman integration from the user integrations catalog — HACS.** The integration is found by a simple search by name, the installation is standard, and after that a reboot of Home Assistant is required.

**The inverter integration itself at this stage comes down to specifying its IP address on your local network.** I left all other parameters at their defaults — in my case this turned out to be completely sufficient for correct operation.

One more important tip — be sure to закрепите (зафіксуйте) the inverter's IP address on the router. If you don't do this, then when the router is rebooted or its firmware is updated, the automatically issued addresses may change, and the integration in Home Assistant will simply stop working. And since the inverter is a key element of the power system, it is better to avoid such situations.

**The integration receives from the inverter - a very large amount of data - in my case - 203 entities.** Just to list them - would require a separate video. Therefore, the overview part will be as compact as possible, and in detail I will talk about those entities that I use in my scenarios.

**Main sensors:** battery parameters, charge, current, power, voltage and temperature, as well as the statuses of the inverter itself and the connection to the grid. These are the data that give a general understanding of the current state — whether the system is operating stably, what mode the battery is in, and what load is currently passing through the inverter.

**Detailed picture by phases:** voltage, current, and power for each line separately, as well as the total home consumption. For a three-phase system, such detail is critically important — it allows you to control load balancing and understand the system's behavior under different consumption scenarios.

**Extended block of settings:** battery operating parameters (voltage thresholds, current limits, interaction mode with grid, wake-up parameters), generator parameters, export limits, work with grid limits, Smart Load functions, and programmable time intervals.

**What the author uses daily:**
- Grid and phase parameters: whether external power is present, power and voltages on each phase
- Inverter output: how much the load consumes in total and by phases
- Energy flow diagram and key battery parameters: home powered from grid or battery, charging or discharging, SOC and power
- Statistics: time of last outages
- Control of operating modes

**Important feature of three-phase hybrid inverter — automatic phase balancing.** Regardless of how the load is currently distributed across phases, at the input from the city grid - power is distributed evenly, which removes the risk of phase imbalance.

---

## Логіка (Logic package)

**Entities stored in history:** grid presence, input and output power, voltage, battery status (out of 200+ entities).

**Helpers:**
- Input boolean for automatic shutdown of high-power loads at low battery
- Two date/time input fields for recording power loss and restoration times

**Template sensors:**
- Binary sensor: battery < 40%, no grid, shutdown mode enabled
- Two sensors for power-flow-card-plus (charge/discharge separation)

**Automations:**
1. **Record power loss/restoration time** — trigger on binary sensor (grid status), 1 min delay
2. **Notification on power loss** — duration of previous supply period, battery SOC
3. **Notification on power restoration** — duration of outage, voltage on phases
4. **Daily report** (7:00) — history stats: time with/without electricity yesterday
5. **Auto shutdown of high-power loads** — when battery < 40%, no grid, mode enabled → notify + turn off water heaters, electric heater
6. **Control automation** — when high-power load turns on during low battery → auto turn off
7. **Resume** — 30 sec after grid restored → turn on water heaters if heating mode enabled

---

## Корисні посилання з опису

- Текстовий файл уроку: https://kvazis.link/jsdfhc
- Deye на Aliexpress, NKON
- Solarman integration в HACS
