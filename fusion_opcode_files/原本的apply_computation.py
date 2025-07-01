# 原本的apply_computation逻辑如下：

    # -- state transition -- #
    @classmethod
    def apply_computation(
        cls,
        state: StateAPI,
        message: MessageAPI,
        transaction_context: TransactionContextAPI,
        parent_computation: Optional[ComputationAPI] = None,
    ) -> ComputationAPI:
        with cls(state, message, transaction_context) as computation:
            if computation.is_origin_computation:
                # If origin computation, reset contracts_created
                computation.contracts_created = []

                if message.is_create:
                    # If computation is from a create transaction, consume initcode gas
                    # if >= Shanghai. CREATE and CREATE2 are handled in the opcode
                    # implementations.
                    cls.consume_initcode_gas_cost(computation)

            if parent_computation is not None:
                # If this is a child computation (has a parent computation), inherit the
                # contracts_created
                computation.contracts_created = parent_computation.contracts_created

            if message.is_create:
                # For all create messages, append the storage address to the
                # contracts_created list
                computation.contracts_created.append(message.storage_address)

            # Early exit on pre-compiles
            precompile = computation.precompiles.get(message.code_address, NO_RESULT)
            if precompile is not NO_RESULT:
                if not message.is_delegation:
                    precompile(computation)
                return computation

            show_debug2 = computation.logger.show_debug2

            opcode_lookup = computation.opcodes
            for opcode in computation.code:
                try:
                    opcode_fn = opcode_lookup[opcode]
                except KeyError:
                    opcode_fn = InvalidOpcode(opcode)

                if show_debug2:
                    # We dig into some internals for debug logs
                    base_comp = cast(BaseComputation, computation)

                    try:
                        mnemonic = opcode_fn.mnemonic
                    except AttributeError:
                        mnemonic = opcode_fn.__wrapped__.mnemonic  # type: ignore

                    computation.logger.debug2(
                        f"OPCODE: 0x{opcode:x} ({mnemonic}) | "
                        f"pc: {max(0, computation.code.program_counter - 1)} | "
                        f"stack: {base_comp._stack}"
                    )

                try:
                    opcode_fn(computation=computation)
                except Halt:
                    break

        return computation
