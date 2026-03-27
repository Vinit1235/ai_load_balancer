"""
Agent Instruction Wrapper

Provides context and guidelines for AI agents to write better code
and self-correct when mistakes are made.
"""

import json
import logging
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from shared.self_correction import SelfCorrectionEngine, RetryConfig, ErrorContext
from ai.code_validator import CodeValidator, ValidationLevel, ValidationResult

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Status of agent tasks"""
    PENDING = "pending"
    VALIDATING = "validating"
    EXECUTING = "executing"
    CORRECTING = "correcting"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentTask:
    """Represents a task assigned to an agent"""
    task_id: str
    task_type: str
    description: str
    code: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    max_attempts: int = 3
    errors: List[ErrorContext] = field(default_factory=list)
    corrections: List[str] = field(default_factory=list)
    validation_results: List[ValidationResult] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None


class AgentInstructionWrapper:
    """
    Wraps agent instructions with self-correction capabilities.
    
    This class:
    1. Validates code before execution
    2. Catches and parses errors
    3. Attempts automatic fixes
    4. Provides feedback loops for agents
    5. Tracks correction history
    """
    
    # System prompt additions for self-correcting behavior
    SELF_CORRECTION_PROMPT = """
## Self-Correction Guidelines

You are an AI agent with self-correction capabilities. Follow these guidelines:

### Before Writing Code:
1. **Think step by step** about what the code needs to do
2. **Consider edge cases** and potential failure points
3. **Plan error handling** before implementation
4. **Check dependencies** - ensure all imports are available

### While Writing Code:
1. **Use type hints** for function parameters and returns
2. **Add docstrings** to functions and classes
3. **Include input validation** for functions that accept user data
4. **Use try-except** for operations that can fail (file I/O, network, etc.)
5. **Log important events** using the logging module

### Code Structure Best Practices:
```python
# DO: Use explicit imports
from typing import Optional, List, Dict
import logging

# DO: Add type hints and docstrings
def process_data(items: List[str]) -> Dict[str, int]:
    \"\"\"
    Process a list of items and return counts.
    
    Args:
        items: List of string items to process
        
    Returns:
        Dictionary mapping items to their counts
        
    Raises:
        ValueError: If items is empty
    \"\"\"
    if not items:
        raise ValueError("Items list cannot be empty")
    
    result = {}
    for item in items:
        result[item] = result.get(item, 0) + 1
    return result

# DO: Use guard clauses for early returns
def get_user(user_id: Optional[str]) -> Optional[dict]:
    if not user_id:
        return None
    
    if not user_id.isalnum():
        logger.warning(f"Invalid user_id format: {user_id}")
        return None
    
    # Main logic here
    return {"id": user_id}
```

### If You Make a Mistake:
1. **Acknowledge the error** - don't hide it
2. **Analyze the root cause** - understand why it happened
3. **Apply the fix** - make minimal, targeted changes
4. **Verify the fix** - run validation again
5. **Document what went wrong** - for future reference

### Common Mistakes to Avoid:
- ❌ Forgetting to close files/connections
- ❌ Not handling None values
- ❌ Catching bare exceptions (use specific types)
- ❌ Hardcoding values that should be configurable
- ❌ Not validating user input
- ❌ Ignoring error return values
- ❌ Using mutable default arguments

### Error Recovery Patterns:
```python
# Pattern 1: Retry with backoff
import time

def fetch_with_retry(url: str, max_retries: int = 3) -> Optional[str]:
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                logger.error(f"Failed after {max_retries} attempts: {e}")
                raise

# Pattern 2: Graceful degradation
def process_with_fallback(data: dict) -> str:
    try:
        return advanced_processing(data)
    except ProcessingError:
        logger.warning("Advanced processing failed, using fallback")
        return simple_processing(data)

# Pattern 3: Validation wrapper
def validate_and_process(input_data: Any) -> Result:
    # Validate first
    validation_errors = validate(input_data)
    if validation_errors:
        return Result(success=False, errors=validation_errors)
    
    # Then process
    try:
        output = process(input_data)
        return Result(success=True, data=output)
    except Exception as e:
        return Result(success=False, errors=[str(e)])
```
"""

    def __init__(
        self,
        correction_engine: Optional[SelfCorrectionEngine] = None,
        code_validator: Optional[CodeValidator] = None,
        max_correction_attempts: int = 3
    ):
        """
        Initialize the instruction wrapper.
        
        Args:
            correction_engine: Engine for error handling and retries
            code_validator: Validator for code quality checks
            max_correction_attempts: Max attempts to fix code
        """
        self.correction_engine = correction_engine or SelfCorrectionEngine()
        self.code_validator = code_validator or CodeValidator(auto_fix=True)
        self.max_correction_attempts = max_correction_attempts
        
        self.active_tasks: Dict[str, AgentTask] = {}
        self.completed_tasks: List[AgentTask] = []
    
    def get_enhanced_prompt(self, base_prompt: str) -> str:
        """
        Enhance a base prompt with self-correction guidelines.
        
        Args:
            base_prompt: Original task prompt
            
        Returns:
            Enhanced prompt with correction guidelines
        """
        return f"""{self.SELF_CORRECTION_PROMPT}

---

## Your Current Task:

{base_prompt}

---

Remember: If your code has errors, they will be caught and you'll have a chance to fix them.
Write clean, validated code on the first attempt to minimize corrections needed.
"""
    
    def create_task(
        self,
        task_id: str,
        task_type: str,
        description: str,
        max_attempts: int = None
    ) -> AgentTask:
        """
        Create a new agent task.
        
        Args:
            task_id: Unique task identifier
            task_type: Type of task
            description: What the agent should do
            max_attempts: Override default max attempts
            
        Returns:
            Created AgentTask
        """
        task = AgentTask(
            task_id=task_id,
            task_type=task_type,
            description=description,
            max_attempts=max_attempts or self.max_correction_attempts
        )
        self.active_tasks[task_id] = task
        logger.info(f"Created task {task_id}: {task_type}")
        return task
    
    def submit_code(
        self,
        task_id: str,
        code: str,
        execute: bool = True,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Submit code for a task with validation and potential correction.
        
        Args:
            task_id: The task this code is for
            code: The generated code
            execute: Whether to execute after validation
            context: Optional execution context
            
        Returns:
            Result dictionary with status and any errors/fixes
        """
        if task_id not in self.active_tasks:
            return {"success": False, "error": f"Task {task_id} not found"}
        
        task = self.active_tasks[task_id]
        task.code = code
        task.attempts += 1
        task.status = TaskStatus.VALIDATING
        
        result = {
            "task_id": task_id,
            "attempt": task.attempts,
            "success": False,
            "validation": None,
            "errors": [],
            "corrections": [],
            "final_code": code
        }
        
        # Step 1: Validate the code
        validation = self.code_validator.validate(
            code,
            level=ValidationLevel.STATIC
        )
        result["validation"] = {
            "is_valid": validation.is_valid,
            "errors": validation.errors,
            "warnings": validation.warnings
        }
        task.validation_results.append(validation)
        
        if not validation.is_valid:
            task.status = TaskStatus.CORRECTING
            
            # Try to repair
            repair_result = self.code_validator.repair_code(
                code,
                max_attempts=self.max_correction_attempts,
                target_level=ValidationLevel.STATIC
            )
            
            if repair_result.is_valid and repair_result.fixed_code:
                code = repair_result.fixed_code
                result["final_code"] = code
                result["corrections"] = repair_result.fixes_applied
                task.corrections.extend(repair_result.fixes_applied)
                task.code = code
                
                logger.info(
                    f"Task {task_id}: Code repaired with "
                    f"{len(repair_result.fixes_applied)} fixes"
                )
            else:
                # Could not repair
                result["errors"] = repair_result.errors
                
                if task.attempts < task.max_attempts:
                    result["needs_resubmit"] = True
                    result["guidance"] = self._generate_fix_guidance(
                        code, 
                        repair_result.errors
                    )
                else:
                    task.status = TaskStatus.FAILED
                    result["task_failed"] = True
                
                return result
        
        # Step 2: Execute if requested
        if execute:
            task.status = TaskStatus.EXECUTING
            
            success, exec_result, errors = self.correction_engine.execute_with_retry(
                func=self._execute_code,
                args=(code, context),
                config=RetryConfig(max_retries=2),
                on_error=lambda e: self._handle_execution_error(task, e)
            )
            
            if success:
                result["success"] = True
                result["execution_result"] = exec_result
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now()
                
                # Move to completed
                self.completed_tasks.append(task)
                del self.active_tasks[task_id]
            else:
                result["errors"] = [
                    {"type": e.error_type, "message": e.error_message}
                    for e in errors
                ]
                task.errors.extend(errors)
                
                if task.attempts < task.max_attempts:
                    result["needs_resubmit"] = True
                    result["guidance"] = self._generate_fix_guidance(
                        code,
                        [e.error_message for e in errors]
                    )
                else:
                    task.status = TaskStatus.FAILED
                    result["task_failed"] = True
        else:
            # Just validation, code passed
            result["success"] = True
            task.status = TaskStatus.COMPLETED
        
        return result
    
    def _execute_code(
        self,
        code: str,
        context: Optional[Dict[str, Any]]
    ) -> Any:
        """Execute code in a controlled environment"""
        # Create execution namespace
        exec_globals = {
            "__builtins__": __builtins__,
            "context": context or {}
        }
        exec_locals = {}
        
        # Execute the code
        exec(code, exec_globals, exec_locals)
        
        # Return any defined 'result' variable or the locals
        return exec_locals.get("result", exec_locals)
    
    def _handle_execution_error(
        self,
        task: AgentTask,
        error: ErrorContext
    ) -> Optional[str]:
        """Handle execution error and attempt fix"""
        if not task.code:
            return None
        
        # Try to auto-fix
        success, fixed_code = self.correction_engine.attempt_auto_fix(
            task.code,
            error
        )
        
        if success and fixed_code:
            task.code = fixed_code
            task.corrections.append(
                f"Fixed {error.error_type}: {error.error_message[:50]}"
            )
            return fixed_code
        
        return None
    
    def _generate_fix_guidance(
        self,
        code: str,
        errors: List[str]
    ) -> str:
        """Generate guidance for the agent to fix errors"""
        guidance = [
            "## Fix Required",
            "",
            "Your code has errors that could not be automatically fixed.",
            "Please review and resubmit.",
            "",
            "### Errors Found:"
        ]
        
        for error in errors:
            guidance.append(f"- {error}")
        
        guidance.extend([
            "",
            "### Suggestions:",
            "1. Check the line numbers mentioned in errors",
            "2. Verify all variables are defined before use",
            "3. Ensure all imports are at the top of the file",
            "4. Check for missing colons, brackets, or parentheses",
            "5. Verify function signatures match their calls",
            "",
            "### Your Current Code:",
            "```python",
            code,
            "```"
        ])
        
        return '\n'.join(guidance)
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a task"""
        task = self.active_tasks.get(task_id)
        if not task:
            # Check completed
            for t in self.completed_tasks:
                if t.task_id == task_id:
                    task = t
                    break
        
        if not task:
            return None
        
        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "attempts": task.attempts,
            "max_attempts": task.max_attempts,
            "errors_count": len(task.errors),
            "corrections_count": len(task.corrections),
            "created_at": task.created_at.isoformat(),
            "completed_at": task.completed_at.isoformat() if task.completed_at else None
        }
    
    def get_correction_summary(self) -> Dict[str, Any]:
        """Get summary of all corrections made"""
        all_tasks = list(self.active_tasks.values()) + self.completed_tasks
        
        total_attempts = sum(t.attempts for t in all_tasks)
        total_corrections = sum(len(t.corrections) for t in all_tasks)
        total_errors = sum(len(t.errors) for t in all_tasks)
        
        successful = len([t for t in all_tasks if t.status == TaskStatus.COMPLETED])
        failed = len([t for t in all_tasks if t.status == TaskStatus.FAILED])
        
        return {
            "total_tasks": len(all_tasks),
            "successful": successful,
            "failed": failed,
            "active": len(self.active_tasks),
            "total_attempts": total_attempts,
            "total_corrections": total_corrections,
            "total_errors": total_errors,
            "average_attempts_per_task": total_attempts / max(1, len(all_tasks)),
            "correction_engine_stats": self.correction_engine.get_correction_stats()
        }


# Task-specific instruction templates
TASK_INSTRUCTIONS = {
    "code_generation": """
You are generating code for a specific task.

REQUIREMENTS:
1. Write complete, runnable code
2. Include all necessary imports at the top
3. Add error handling for operations that can fail
4. Include type hints and docstrings
5. Follow PEP 8 style guidelines

OUTPUT FORMAT:
```python
# Your code here
```
""",

    "code_review": """
You are reviewing existing code for issues.

CHECKLIST:
1. Security vulnerabilities
2. Error handling gaps
3. Performance issues
4. Code style problems
5. Missing documentation

OUTPUT FORMAT:
```json
{
    "issues": [...],
    "suggestions": [...],
    "severity": "low|medium|high"
}
```
""",

    "bug_fix": """
You are fixing a bug in existing code.

APPROACH:
1. Understand the error first
2. Find the root cause
3. Apply minimal fix
4. Add test for the fix
5. Verify fix works

OUTPUT FORMAT:
```python
# Fixed code
```

EXPLANATION:
- What was the bug
- Why it happened  
- How you fixed it
""",

    "refactoring": """
You are refactoring existing code.

GOALS:
1. Improve readability
2. Reduce complexity
3. Enhance maintainability
4. Keep behavior identical

RULES:
- Test before and after
- Make incremental changes
- Document changes made
"""
}


def get_task_instruction(task_type: str) -> str:
    """Get instruction template for a task type"""
    return TASK_INSTRUCTIONS.get(task_type, TASK_INSTRUCTIONS["code_generation"])


# Singleton instance
agent_wrapper = AgentInstructionWrapper()
