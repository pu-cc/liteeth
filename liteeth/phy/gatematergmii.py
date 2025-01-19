#
# This file is part of LiteEth.
#
# Copyright (c) 2025 Patrick Urban <support@colognechip.com>
# Based on ecp5rgmii:
#   Copyright (c) 2019-2023 Florent Kermarrec <florent@enjoy-digital.fr>
#   Copyright (c) 2020 Shawn Hoffman <godisgovernment@gmail.com>
# SPDX-License-Identifier: BSD-2-Clause

# RGMII PHY for Cologne Chip GateMate FPGA

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer

from litex.gen import *

from litex.build.io import DDROutput, DDRInput

from liteeth.common import *
from liteeth.phy.common import *


# Timing data for each performance mode
iodly_timing = {
    "speed":    {"best": 30e-12, "typ": 38e-12, "worst": 50e-12},
    "economy":  {"best": 38e-12, "typ": 50e-12, "worst": 65e-12},
    "lowpower": {"best": 50e-12, "typ": 65e-12, "worst": 85e-12},
}

class LiteEthPHYRGMIITX(LiteXModule):
    def __init__(self, pads):
        self.sink = sink = stream.Endpoint(eth_phy_description(8))

        tx_ctl_oddrx1f  = Signal()
        tx_data_oddrx1f = Signal(4)

        self.specials += [
            DDROutput(
                clk = ClockSignal("eth_tx"),
                i1  = sink.valid,
                i2  = sink.valid,
                o   = tx_ctl_oddrx1f,
            ),
            Instance("CC_OBUF",
                p_DELAY_OBF = 0,
                i_A         = tx_ctl_oddrx1f,
                o_O         = pads.tx_ctl,
            )
        ]
        for i in range(4):
            self.specials += [
                DDROutput(
                    clk = ClockSignal("eth_tx"),
                    i1  = sink.data[i],
                    i2  = sink.data[4+i],
                    o   = tx_data_oddrx1f[i],
                ),
                Instance("CC_OBUF",
                    p_DELAY_OBF = 0,
                    i_A         = tx_data_oddrx1f[i],
                    o_O         = pads.tx_data[i],
                )
            ]
        self.comb += sink.ready.eq(1)

class LiteEthPHYRGMIIRX(LiteXModule):
    def __init__(self, pads, rx_delay=2e-9, perf_mode="undefined"):
        self.source = source = stream.Endpoint(eth_phy_description(8))

        self._iodly = iodly_timing[perf_mode.lower()]["worst"]

        rx_delay_taps = int(rx_delay/self._iodly)
        assert rx_delay_taps < 16

        rx_ctl_delayf  = Signal()
        rx_ctl         = Signal(2)
        rx_ctl_reg     = Signal(2)
        rx_data_delayf = Signal(4)
        rx_data        = Signal(8)
        rx_data_reg    = Signal(8)

        self.specials += [
            Instance("CC_IBUF",
                p_DELAY_IBF = rx_delay_taps,
                i_I         = pads.rx_ctl,
                o_Y         = rx_ctl_delayf,
            ),
            DDRInput(
                clk = ClockSignal("eth_rx"),
                i   = rx_ctl_delayf,
                o1  = rx_ctl[0],
                o2  = rx_ctl[1],
            )
        ]
        self.sync += rx_ctl_reg.eq(rx_ctl)
        for i in range(4):
            self.specials += [
                Instance("CC_IBUF",
                    p_DELAY_IBF = rx_delay_taps,
                    i_I         = pads.rx_data[i],
                    o_Y         = rx_data_delayf[i]),
                DDRInput(
                    clk = ClockSignal("eth_rx"),
                    i   = rx_data_delayf[i],
                    o1  = rx_data[i],
                    o2  = rx_data[i+4],
                )
            ]
        self.sync += rx_data_reg.eq(rx_data)

        rx_ctl_reg_d = Signal(2)
        self.sync += rx_ctl_reg_d.eq(rx_ctl_reg)

        last = Signal()
        self.comb += last.eq(~rx_ctl_reg[0] & rx_ctl_reg_d[0])
        self.sync += [
            source.valid.eq(rx_ctl_reg[0]),
            source.data.eq(rx_data_reg)
        ]
        self.comb += source.last.eq(last)

class LiteEthPHYRGMIICRG(LiteXModule):
    def __init__(self, clock_pads, pads, with_hw_init_reset, tx_delay=2e-9, perf_mode="undefined"):
        self._reset = CSRStorage()

        # RX Clock
        self.cd_eth_rx = ClockDomain()
        self.comb += self.cd_eth_rx.clk.eq(clock_pads.rx)

        # TX Clock
        self.cd_eth_tx = ClockDomain()
        self.comb += self.cd_eth_tx.clk.eq(self.cd_eth_rx.clk)

        self._iodly = iodly_timing[perf_mode.lower()]["worst"]

        tx_delay_taps = int(tx_delay/self._iodly)
        assert tx_delay_taps < 16

        eth_tx_clk_o = Signal()
        self.specials += [
            Instance("CC_ODDR",
                p_CLK_INV = 0,
                i_CLK     = ClockSignal("eth_tx"),
                i_DDR     = ClockSignal("eth_tx"),
                i_D0      = 0,
                i_D1      = 1,
                o_Q       = eth_tx_clk_o,
            ),
            Instance("CC_OBUF",
                p_DELAY_OBF = tx_delay_taps,
                i_A         = eth_tx_clk_o,
                o_O         = clock_pads.tx,
            ),
        ]

        # Reset
        self.reset = reset = Signal()
        if with_hw_init_reset:
            self.hw_reset = LiteEthPHYHWReset()
            self.comb += reset.eq(self._reset.storage | self.hw_reset.reset)
        else:
            self.comb += reset.eq(self._reset.storage)
        if hasattr(pads, "rst_n"):
            self.comb += pads.rst_n.eq(~reset)
        self.specials += [
            AsyncResetSynchronizer(self.cd_eth_tx, reset),
            AsyncResetSynchronizer(self.cd_eth_rx, reset),
        ]

class LiteEthPHYRGMII(LiteXModule):
    dw          = 8
    tx_clk_freq = 125e6
    rx_clk_freq = 125e6
    def __init__(self, clock_pads, pads, with_hw_init_reset=True,
        tx_delay           = 0e-9,
        rx_delay           = 0e-9,
        perf_mode          = "undefined"
        ):
        self.crg = LiteEthPHYRGMIICRG(clock_pads, pads, with_hw_init_reset, tx_delay, perf_mode)
        self.tx  = ClockDomainsRenamer("eth_tx")(LiteEthPHYRGMIITX(pads))
        self.rx  = ClockDomainsRenamer("eth_rx")(LiteEthPHYRGMIIRX(pads, rx_delay))
        self.sink, self.source = self.tx.sink, self.rx.source

        if hasattr(pads, "mdc"):
            self.mdio = LiteEthPHYMDIO(pads)
