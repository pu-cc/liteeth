#
# This file is part of MiSoC and has been adapted/modified for LiteEth.
#
# Copyright (c) 2018 Sebastien Bourdeauducq <sb@m-labs.hk>
# Copyright (c) 2020-2024 Florent Kermarrec <florent@enjoy-digital.fr>
# Copyright (c) 2023 Sergey Razumov <cyntem@gmail.com>
# Copyright (c) 2025 Patrick Urban <support@colognechip.com>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer
from migen.genlib.cdc import PulseSynchronizer

from litex.gen import *

from litex.soc.cores.clock.colognechip import GateMatePLL

from liteeth.common import *
from liteeth.phy.pcs_1000basex import *

# GateMate_1000BASEX PHY ---------------------------------------------------------------------------------

class GateMate_1000BASEX(LiteXModule):
    dw          = 8
    linerate    = 1.25e9
    rx_clk_freq = 125e6
    tx_clk_freq = 125e6
    def __init__(self, sys_clk_freq, refclk_freq=100e6, with_csr=True,
        tx_polarity    = 0,
        rx_polarity    = 0,
    ):
        assert refclk_freq in [100e6, 125e6]
        self.pcs = pcs = PCS(lsb_first=True)

        self.sink    = pcs.sink
        self.source  = pcs.source
        self.link_up = pcs.link_up

        self.cd_eth_tx      = ClockDomain()
        self.cd_eth_rx      = ClockDomain()
        self.cd_eth_tx_half = ClockDomain(reset_less=True)
        self.cd_eth_rx_half = ClockDomain(reset_less=True)

        # for specifying clock constraints. 62.5MHz clocks.
        self.txoutclk = Signal()
        self.rxoutclk = Signal()

        self.reset = Signal()
        if with_csr:
            self.add_csr()

        # # #

        # SerDes transceiver.
        adpll_reset   = Signal(reset=1)

        tx_reset      = Signal()
        tx_data       = Signal(20)
        tx_reset_done = Signal()

        rx_reset      = Signal()
        rx_cm_reset   = Signal(reset=1)
        rx_data       = Signal(20)
        rx_reset_done = Signal()

        adpll_clk = Signal()

        # SerDes Register File
        rfaddr = Signal(8)
        rfen   = Signal()
        rfdi   = Signal(16)
        rfrdy  = Signal()
        rfdo   = Signal(16)
        rfwe   = Signal()

        adpll_settings = {
            100e6: {
                'fcntrl': 0xA, #0x1a, # 0x0A: 5, 0x1A: 10 # divide by 5 to generate o_PLL_CLK_O with 125MHz
                'main_divsel': 0x1b,
                'out_divsel': {1.25e9 : 3, 3.125e9 : 1}[self.linerate],
            },
            125e6: {
                'fcntrl': 0x1a,
                'main_divsel': 0x1a,
                'out_divsel': {1.25e9 : 3, 3.125e9 : 1}[self.linerate],
            }
        }

        adpll = adpll_settings.get(refclk_freq)

        # Work around Python's 255 argument limitation.
        self.serdes_params = serdes_params = dict(
            p_RX_RESET_TIMER_PRESC = 0,
            p_RX_RESET_OVR = 0,
            p_RX_RESET = 0,

            p_RX_PCS_RESET_TIME = 3,
            p_RX_RESET_DONE_GATE = 0,

            # RX Analog Frontend
            p_RX_PMA_RESET_TIME = 3,
            p_RX_EI_BIAS = 4,
            p_RX_EI_BW_SEL = 4,
            p_RX_EN_EI_DETECTOR_OVR = 0,
            p_RX_EN_EI_DETECTOR = 0,
            p_RX_AFE_PEAK = 16,
            p_RX_AFE_GAIN = 8,
            p_RX_AFE_VCMSEL = 4,
            p_RX_CALIB_EN = 1,
            p_RX_CALIB_OVR = 0,
            p_RX_CALIB_VAL = 0,
            p_RX_RTERM_VCMSEL = 4,
            p_RX_RTERM_PD = 0,

            # RX CDR
            p_RX_WAIT_CDR_LOCK = 0, # CHECK
            p_RX_CDR_CKP = 0xF8,
            p_RX_CDR_CKI = 0,
            p_RX_CDR_TRANS_TH = 128,
            p_RX_CDR_LOCK_CFG = 0x0B,
            p_RX_CDR_FREQ_ACC = 0,
            p_RX_CDR_PHASE_ACC = 0,
            p_RX_CDR_SET_ACC_CONFIG = 0,
            p_RX_CDR_FORCE_LOCK = 1,
            p_RX_CDR_RESET_TIME = 3,
            p_RX_CDR_RESET_OVR = 0,
            p_RX_CDR_RESET = 0,

            # RX Byte and Word Alignment
            p_RX_ALIGN_MCOMMA_VALUE = 0x283,
            p_RX_MCOMMA_ALIGN_OVR = 0,
            p_RX_MCOMMA_ALIGN = 0,
            p_RX_ALIGN_PCOMMA_VALUE = 0x17C,
            p_RX_PCOMMA_ALIGN_OVR = 0,
            p_RX_PCOMMA_ALIGN = 0,
            p_RX_ALIGN_COMMA_WORD = 1, # 16 bit
            p_RX_ALIGN_COMMA_ENABLE = 0x3FF,
            p_RX_SLIDE_MODE = 0,
            p_RX_COMMA_DETECT_EN_OVR = 0,
            p_RX_COMMA_DETECT_EN = 1,
            p_RX_SLIDE = 0,
            p_RX_BYTE_REALIGN = 1,

            # RX Equalizer
            p_RX_EQA_RESET_TIME = 3,
            p_RX_EQA_RESET_OVR = 0,
            p_RX_EQA_RESET = 0,
            p_RX_EQA_CKP_LF = 0xA3,
            p_RX_EQA_CKP_HF = 0xA3,
            p_RX_EQA_CKP_OFFSET = 0x01,
            p_RX_EN_EQA = 0,
            p_RX_EQA_LOCK_CFG = 0,
            p_RX_TH_MON1 = 8,
            p_RX_EN_EQA_EXT_VALUE = 0,
            p_RX_TH_MON2 = 8,
            p_RX_TAPW = 8,
            p_RX_AFE_OFFSET = 8,
            p_RX_EQA_CONFIG = 0x01C0,
            p_RX_MON_PH_OFFSET = 0,

            # RX Margin Analysis
            p_RX_EYE_MEAS_EN = 0,
            p_RX_EYE_MEAS_CFG = 0,

            # RX Elatic Buffer / Clock Correction
            p_RX_BUF_RESET_TIME = 3,
            p_RX_BUF_RESET_OVR = 0,
            p_RX_BUF_RESET = 0,
            p_RX_BUF_BYPASS = 0,
            p_RX_CLKCOR_USE = 0,
            p_RX_CLKCOR_MIN_LAT = 32,
            p_RX_CLKCOR_MAX_LAT = 39,
            p_RX_CLKCOR_SEQ_1_0 = 0x1F7,
            p_RX_CLKCOR_SEQ_1_1 = 0x1F7,
            p_RX_CLKCOR_SEQ_1_2 = 0x1F7,
            p_RX_CLKCOR_SEQ_1_3 = 0x1F7,

            # TX+RX PRBS
            p_TX_PRBS_OVR = 0,
            p_TX_PRBS_SEL = 0,
            p_TX_PRBS_FORCE_ERR = 0,
            p_RX_PRBS_OVR = 0,
            p_RX_PRBS_SEL = 0,
            p_RX_PRBS_CNT_RESET = 0,

            # TX+RX Loopback
            p_TX_LOOPBACK_OVR = 0,
            p_TX_PMA_LOOPBACK = 0,
            p_TX_PCS_LOOPBACK = 0,
            p_RX_LOOPBACK_OVR = 0,
            p_RX_PMA_LOOPBACK = 0,
            p_RX_PCS_LOOPBACK = 0,

            # TX+RX Powerdown
            p_TX_POWER_DOWN_OVR = 0,
            p_TX_POWER_DOWN_N = 1,
            p_TX_ELEC_IDLE_OVR = 0,
            p_TX_ELEC_IDLE = 0,
            p_RX_POWER_DOWN_OVR = 0,
            p_RX_POWER_DOWN_N = 1,

            # TX+RX 8B10B
            p_TX_8B10B_EN_OVR = 0,
            p_TX_8B10B_EN = 0,
            p_RX_8B10B_EN_OVR = 0,
            p_RX_8B10B_EN = 0,
            p_RX_8B10B_BYPASS = 0,

            # TX+RX Datapath
            p_TX_DATAPATH_SEL = 0, # 20 bit
            p_RX_DATAPATH_SEL = 0, # 20 bit

            # TX+RX Polarity Control
            p_RX_POLARITY_OVR = 0,
            p_RX_POLARITY = 0,
            p_TX_POLARITY_OVR = 0,
            p_TX_POLARITY = 0,

            p_RX_PMA_RESET_OVR = 0,
            p_RX_PMA_RESET = 0,
            p_RX_PCS_RESET_OVR = 0,
            p_RX_PCS_RESET = 0,
            p_TX_SEL_PRE = 0,
            p_TX_SEL_POST = 0,
            p_TX_AMP = 15,
            p_TX_BRANCH_EN_PRE = 0,
            p_TX_BRANCH_EN_MAIN = 0x3F,
            p_TX_BRANCH_EN_POST = 0,
            p_TX_TAIL_CASCODE = 4,
            p_TX_DC_ENABLE = 63,
            p_TX_DC_OFFSET = 8,
            p_TX_CM_RAISE = 0,
            p_TX_CM_THRESHOLD_0 = 14,
            p_TX_CM_THRESHOLD_1 = 16,
            p_TX_SEL_PRE_EI = 0,
            p_TX_SEL_POST_EI = 0,
            p_TX_AMP_EI = 15,
            p_TX_BRANCH_EN_PRE_EI = 0,
            p_TX_BRANCH_EN_MAIN_EI = 0x3F,
            p_TX_BRANCH_EN_POST_EI = 0,
            p_TX_TAIL_CASCODE_EI = 4,
            p_TX_DC_ENABLE_EI = 63,
            p_TX_DC_OFFSET_EI = 0,
            p_TX_CM_RAISE_EI = 0,
            p_TX_CM_THRESHOLD_0_EI = 14,
            p_TX_CM_THRESHOLD_1_EI = 16,
            p_TX_SEL_PRE_RXDET = 0,
            p_TX_SEL_POST_RXDET = 0,
            p_TX_AMP_RXDET = 15,
            p_TX_BRANCH_EN_PRE_RXDET = 0,
            p_TX_BRANCH_EN_MAIN_RXDET = 0x3F,
            p_TX_BRANCH_EN_POST_RXDET = 0,
            p_TX_TAIL_CASCODE_RXDET = 4,
            p_TX_DC_ENABLE_RXDET = 63,
            p_TX_DC_OFFSET_RXDET = 0,
            p_TX_CM_RAISE_RXDET = 0,
            p_TX_CM_THRESHOLD_0_RXDET = 14,
            p_TX_CM_THRESHOLD_1_RXDET = 16,
            p_TX_CALIB_EN = 0,
            p_TX_CALIB_OVR = 0,
            p_TX_CALIB_VAL = 0,
            p_TX_CM_REG_KI = 0x80,
            p_TX_CM_SAR_EN = 0,
            p_TX_CM_REG_EN = 1,
            p_TX_PMA_RESET_TIME = 3,
            p_TX_PCS_RESET_TIME = 3,
            p_TX_PCS_RESET_OVR = 0,
            p_TX_PCS_RESET = 0,
            p_TX_PMA_RESET_OVR = 0,
            p_TX_PMA_RESET = 0,
            p_TX_RESET_OVR = 0,
            p_TX_RESET = 0,
            p_TX_DETECT_RX_OVR = 0,
            p_TX_DETECT_RX = 0,
            p_TX_DATA_OVR = 0,
            p_TX_DATA_CNT = 0,
            p_TX_DATA_VALID = 0,

            # ADPLL
            p_PLL_EN_ADPLL_CTRL = 1,
            p_PLL_CONFIG_SEL = 1,
            p_PLL_SET_OP_LOCK = 0,
            p_PLL_ENFORCE_LOCK = 0,
            p_PLL_DISABLE_LOCK = 0,
            p_PLL_LOCK_WINDOW = 1,
            p_PLL_FAST_LOCK = 1,
            p_PLL_SYNC_BYPASS = 0,
            p_PLL_PFD_SELECT = 0,
            p_PLL_REF_BYPASS = 0,
            p_PLL_REF_SEL = 1,
            p_PLL_REF_RTERM = 1,
            p_PLL_FCNTRL = adpll['fcntrl'],
            p_PLL_MAIN_DIVSEL = adpll['main_divsel'],
            p_PLL_OUT_DIVSEL = adpll['out_divsel'],
            p_PLL_CI = 3,
            p_PLL_CP = 80,
            p_PLL_AO = 0,
            p_PLL_SCAP = 0,
            p_PLL_FILTER_SHIFT = 2,
            p_PLL_SAR_LIMIT = 2,
            p_PLL_FT = 512,
            p_PLL_OPEN_LOOP = 0,
            p_PLL_SCAP_AUTO_CAL = 1,

            # ADPLL BISC
            p_PLL_BISC_MODE = 5,
            p_PLL_BISC_TIMER_MAX = 15,
            p_PLL_BISC_OPT_DET_IND = 0,
            p_PLL_BISC_PFD_SEL = 0,
            p_PLL_BISC_DLY_DIR = 0,
            p_PLL_BISC_COR_DLY = 1,
            p_PLL_BISC_CAL_SIGN = 0,
            p_PLL_BISC_CAL_AUTO = 1,
            p_PLL_BISC_CP_MIN = 4,
            p_PLL_BISC_CP_MAX = 18,
            p_PLL_BISC_CP_START = 12,
            p_PLL_BISC_DLY_PFD_MON_REF = 0,
            p_PLL_BISC_DLY_PFD_MON_DIV = 2,

            # Misc.
            p_SERDES_ENABLE = 1,
            p_SERDES_AUTO_INIT = 0,
            p_SERDES_TESTMODE = 1
        )
        serdes_params.update(
            # Regfile Ports
            i_REGFILE_CLK_I          = ClockSignal(),
            i_REGFILE_WE_I           = rfwe,
            i_REGFILE_EN_I           = rfen,
            i_REGFILE_ADDR_I         = rfaddr,
            i_REGFILE_DI_I           = rfdi,
            i_REGFILE_MASK_I         = 0xFFFF,
            o_REGFILE_DO_O           = rfdo,
            o_REGFILE_RDY_O          = rfrdy,

            # PLL and Misc. Ports
            i_PLL_RESET_I            = adpll_reset,
            o_PLL_CLK_O              = self.txoutclk, # 125 MHz
            i_LOOPBACK_I             = 0b00,

            # TX
            i_TX_DATA_I              = Cat(tx_data[:8], tx_data[10:18]),
            i_TX_RESET_I             = tx_reset,
            i_TX_PCS_RESET_I         = 0,
            i_TX_PMA_RESET_I         = 0,
            i_TX_POWER_DOWN_N_I      = 1,
            i_TX_POLARITY_I          = tx_polarity,
            i_TX_PRBS_SEL_I          = 0b00,
            i_TX_PRBS_FORCE_ERR_I    = 0,
            i_TX_8B10B_EN_I          = 0,
            i_TX_8B10B_BYPASS_I      = 0x00,
            i_TX_CHAR_IS_K_I         = 0x00,
            i_TX_CHAR_DISPMODE_I     = Cat(tx_data[9], tx_data[19]),
            i_TX_CHAR_DISPVAL_I      = Cat(tx_data[8], tx_data[18]),
            i_TX_ELEC_IDLE_I         = 0,
            i_TX_DETECT_RX_I         = 1,
            i_TX_CLK_I               = ClockSignal("eth_tx_half"),
            o_TX_DETECT_RX_DONE_O    = Open(),
            o_TX_DETECT_RX_PRESENT_O = Open(),
            o_TX_BUF_ERR_O           = Open(),
            o_TX_RESET_DONE_O        = tx_reset_done,

            # RX
            i_RX_CLK_I               = ClockSignal("eth_rx_half"),
            i_RX_RESET_I             = rx_reset,
            i_RX_PMA_RESET_I         = 0,
            i_RX_EQA_RESET_I         = 0,
            i_RX_CDR_RESET_I         = 0,
            i_RX_PCS_RESET_I         = 0,
            i_RX_BUF_RESET_I         = 0,
            i_RX_POWER_DOWN_N_I      = 1,
            i_RX_POLARITY_I          = rx_polarity,
            i_RX_PRBS_SEL_I          = 0b00,
            i_RX_PRBS_CNT_RESET_I    = 0,
            i_RX_8B10B_EN_I          = 0,
            i_RX_8B10B_BYPASS_I      = 0x00,
            i_RX_EN_EI_DETECTOR_I    = 0,
            i_RX_COMMA_DETECT_EN_I   = 1,
            i_RX_SLIDE_I             = 0,
            i_RX_MCOMMA_ALIGN_I      = pcs.align,
            i_RX_PCOMMA_ALIGN_I      = pcs.align,
            o_RX_DATA_O              = Cat(rx_data[:8], rx_data[10:18]),
            o_RX_NOT_IN_TABLE_O      = Open(),
            o_RX_CHAR_IS_COMMA_O     = Open(),
            o_RX_CHAR_IS_K_O         = Cat(rx_data[8], rx_data[18]),
            o_RX_DISP_ERR_O          = Cat(rx_data[9], rx_data[19]),
            o_RX_PRBS_ERR_O          = Open(),
            o_RX_BUF_ERR_O           = Open(),
            o_RX_BYTE_IS_ALIGNED_O   = Open(),
            o_RX_BYTE_REALIGN_O      = Open(),
            o_RX_RESET_DONE_O        = rx_reset_done,
            o_RX_EI_EN_O             = Open(),
            o_RX_CLK_O               = self.rxoutclk
        )

        tx_half_clk = Signal()
        tx_half_toggle = Signal()

        self.sync.eth_tx += tx_half_toggle.eq(~tx_half_toggle)
        self.comb += tx_half_clk.eq(tx_half_toggle)

        self.specials += Instance("CC_BUFG",
            i_I = tx_half_clk,
            o_O = self.cd_eth_tx_half.clk,
        )
        self.specials += Instance("CC_BUFG",
            i_I = self.txoutclk,
            o_O = self.cd_eth_tx.clk,
        )

        # RX CM.
        self.rx_cm = rx_cm = GateMatePLL(perf_mode="speed", lock_req=0)
        rx_cm.register_clkin(self.rxoutclk, self.rx_clk_freq/2, usr_clk_ref=True)
        rx_cm.create_clkout(self.cd_eth_rx_half, self.rx_clk_freq/2, phase=0,   with_reset=False)
        rx_cm.create_clkout(self.cd_eth_rx,      self.rx_clk_freq,   phase=180, with_reset=True) # phase=180 activates CLK180_DOUB
        self.comb += rx_cm.reset.eq(rx_cm_reset)

        #self.specials += AsyncResetSynchronizer(self.cd_eth_tx, tx_reset_done),
        #self.specials += AsyncResetSynchronizer(self.cd_eth_rx, rx_reset_done),

        self.comb += [
            tx_reset.eq(self.reset),
            rx_reset.eq(self.reset)
        ]

        # PLL reset
        pll_reset_cycles = round(30000*sys_clk_freq//1000000000)
        reset_counter    = Signal(max=pll_reset_cycles+1)
        reset_counter.eq(0)
        adpll_reset.eq(1)
        self.sync += [
            If(reset_counter == pll_reset_cycles,
                adpll_reset.eq(0)
            ).Else(
                reset_counter.eq(reset_counter + 1)
            )
        ]

        # Assume CDR lock time is 50,000 UI
        cdr_lock_time = round(sys_clk_freq*50e3/self.linerate)
        cdr_lock_counter = Signal(max=cdr_lock_time+1)
        cdr_locked = Signal()
        self.sync += [
            If(rx_reset,
                cdr_locked.eq(0),
                cdr_lock_counter.eq(0)
            ).Elif(cdr_lock_counter != cdr_lock_time,
                cdr_lock_counter.eq(cdr_lock_counter + 1)
            ).Else(
                cdr_locked.eq(1)
            ),
            rx_cm_reset.eq(~cdr_locked)
        ]

        # Gearbox and PCS connection
        self.gearbox = gearbox = PCSGearbox()
        self.comb += [
            tx_data.eq(gearbox.tx_data_half),
            gearbox.rx_data_half.eq(rx_data),

            gearbox.tx_data.eq(pcs.tbi_tx),
            pcs.tbi_rx.eq(gearbox.rx_data)
        ]

    def add_csr(self):
        self._reset = CSRStorage()
        self.comb += self.reset.eq(self._reset.storage)

    def do_finalize(self):
        self.specials += Instance("CC_SERDES", **self.serdes_params)

# GateMate_2500BASEX PHY ---------------------------------------------------------------------------------

class GateMate_2500BASEX(GateMate_1000BASEX):
    linerate    = 3.125e9
    rx_clk_freq = 312.5e6
    tx_clk_freq = 312.5e6
