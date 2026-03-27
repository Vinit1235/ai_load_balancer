"""
Self-Correction Engine for AI Agents

Provides retry logic, error parsing, validation, and automated fix capabilities
for agents that can make mistakes when writing or executing code.
"""

import logging
import re
import time
import traceback
import ast
import subprocess
import sys
from typing import Dict, Any, Optional, Callable, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Severity levels for errors"""
    LOW = "low"           # Warnings, style issues
    MEDIUM = "medium"     # Recoverable errors
    HIGH = "high"         # Critical errors
    FATAL = "fatal"       # Unrecoverable errors


class ErrorCategory(Enum):
    """Categories of errors for targeted fixing"""
    SYNTAX = "syntax"
    IMPORT = "import"
    RUNTIME = "runtime"
    TYPE = "type"
    LOGIC = "logic"
    NETWORK = "network"
    RESOURCE = "resource"
    UNKNOWN = "unknown"


@dataclass
class ErrorContext:
    """Captures detailed context about an error"""
    error_type: str
    error_message: str
    category: ErrorCategory
    severity: ErrorSeverity
    line_number: Optional[int] = None
    code_snippet: Optional[str] = None
    full_traceback: Optional[str] = None
    suggested_fixes: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class CorrectionResult:
    """Result of a correction attempt"""
    success: bool
    original_error: ErrorContext
    correction_applied: Optional[str] = None
    new_code: Optional[str] = None
    attempts: int = 0
    total_time_seconds: float = 0.0
    final_error: Optional[ErrorContext] = None


class RetryConfig:
    """Configuration for retry behavior"""
    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 30.0,
        exponential_backoff: bool = True,
        backoff_multiplier: float = 2.0,
        retry_on_exceptions: Tuple[type, ...] = (Exception,),
        skip_exceptions: Tuple[type, ...] = ()
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_backoff = exponential_backoff
        self.backoff_multiplier = backoff_multiplier
        self.retry_on_exceptions = retry_on_exceptions
        self.skip_exceptions = skip_exceptions


class SelfCorrectionEngine:
    """
    Core engine for self-correcting agent behavior.
    
    Features:
    - Error parsing and categorization
    - Retry logic with exponential backoff
    - Code validation (syntax, imports, types)
    - Automated fix suggestions
    - LLM-powered code repair (when available)
    """
    
    def __init__(self, llm_client=None):
        """
        Initialize the self-correction engine.
        
        Args:
            llm_client: Optional LLM client for intelligent error fixing
        """
        self.llm_client = llm_client
        self.error_history: List[ErrorContext] = []
        self.correction_stats = {
            "total_errors": 0,
            "successful_corrections": 0,
            "failed_corrections": 0,
            "by_category": {}
        }
        
        # Error pattern matching for common issues
        self.error_patterns = {
            ErrorCategory.SYNTAX: [
                r"SyntaxError:",
                r"IndentationError:",
                r"TabError:",
                r"invalid syntax"
            ],
            ErrorCategory.IMPORT: [
                r"ImportError:",
                r"ModuleNotFoundError:",
                r"No module named"
            ],
            ErrorCategory.TYPE: [
                r"TypeError:",
                r"AttributeError:",
                r"expected .+ but got"
            ],
            ErrorCategory.RUNTIME: [
                r"RuntimeError:",
                r"ValueError:",
                r"KeyError:",
                r"IndexError:",
                r"ZeroDivisionError:"
            ],
            ErrorCategory.NETWORK: [
                r"ConnectionError:",
                r"TimeoutError:",
                r"HTTPError:",
                r"URLError:",
                r"Connection refused"
            ],
            ErrorCategory.RESOURCE: [
                r"MemoryError:",
                r"OSError:",
                r"ResourceExhausted",
                r"out of memory"
            ]
        }
    
    def parse_error(self, error: Exception, code: Optional[str] = None) -> ErrorContext:
        """
        Parse an exception into a structured ErrorContext.
        
        Args:
            error: The exception that occurred
            code: Optional source code where error happened
            
        Returns:
            ErrorContext with parsed error details
        """
        error_type = type(error).__name__
        error_message = str(error)
        tb = traceback.format_exc()
        
        # Determine category
        category = self._categorize_error(error_type, error_message, tb)
        
        # Determine severity
        severity = self._assess_severity(category, error)
        
        # Extract line number
        line_number = self._extract_line_number(tb)
        
        # Get code snippet around error
        code_snippet = None
        if code and line_number:
            code_snippet = self._get_code_snippet(code, line_number)
        
        # Generate fix suggestions
        suggestions = self._generate_suggestions(category, error_message, code_snippet)
        
        context = ErrorContext(
            error_type=error_type,
            error_message=error_message,
            category=category,
            severity=severity,
            line_number=line_number,
            code_snippet=code_snippet,
            full_traceback=tb,
            suggested_fixes=suggestions
        )
        
        self.error_history.append(context)
        self.correction_stats["total_errors"] += 1
        self.correction_stats["by_category"][category.value] = \
            self.correction_stats["by_category"].get(category.value, 0) + 1
        
        return context
    
    def _categorize_error(self, error_type: str, message: str, traceback: str) -> ErrorCategory:
        """Categorize error based on patterns"""
        full_text = f"{error_type}: {message}\n{traceback}"
        
        for category, patterns in self.error_patterns.items():
            for pattern in patterns:
                if re.search(pattern, full_text, re.IGNORECASE):
                    return category
        
        return ErrorCategory.UNKNOWN
    
    def _assess_severity(self, category: ErrorCategory, error: Exception) -> ErrorSeverity:
        """Assess the severity of an error"""
        # Fatal errors (unrecoverable)
        if isinstance(error, (SystemExit, KeyboardInterrupt)):
            return ErrorSeverity.FATAL
        
        if category == ErrorCategory.RESOURCE:
            return ErrorSeverity.HIGH
        
        if category in (ErrorCategory.SYNTAX, ErrorCategory.IMPORT):
            return ErrorSeverity.HIGH
        
        if category == ErrorCategory.TYPE:
            return ErrorSeverity.MEDIUM
        
        if category == ErrorCategory.RUNTIME:
            return ErrorSeverity.MEDIUM
        
        if category == ErrorCategory.NETWORK:
            return ErrorSeverity.MEDIUM
        
        return ErrorSeverity.LOW
    
    def _extract_line_number(self, traceback_str: str) -> Optional[int]:
        """Extract line number from traceback"""
        # Match patterns like "line 42" or "line 42,"
        match = re.search(r'line (\d+)', traceback_str)
        if match:
            return int(match.group(1))
        return None
    
    def _get_code_snippet(self, code: str, line_number: int, context_lines: int = 3) -> str:
        """Get code snippet around the error line"""
        lines = code.split('\n')
        start = max(0, line_number - context_lines - 1)
        end = min(len(lines), line_number + context_lines)
        
        snippet_lines = []
        for i in range(start, end):
            marker = '>>> ' if i == line_number - 1 else '    '
            snippet_lines.append(f"{marker}{i+1}: {lines[i]}")
        
        return '\n'.join(snippet_lines)
    
    def _generate_suggestions(
        self, 
        category: ErrorCategory, 
        message: str, 
        code_snippet: Optional[str]
    ) -> List[str]:
        """Generate fix suggestions based on error type"""
        suggestions = []
        
        if category == ErrorCategory.SYNTAX:
            suggestions.extend([
                "Check for missing parentheses, brackets, or quotes",
                "Verify proper indentation (use 4 spaces)",
                "Look for unclosed strings or comments"
            ])
            
        elif category == ErrorCategory.IMPORT:
            module_match = re.search(r"No module named '(\w+)'", message)
            if module_match:
                module = module_match.group(1)
                suggestions.append(f"Install missing module: pip install {module}")
            suggestions.append("Verify the import path is correct")
            suggestions.append("Check if the module is in PYTHONPATH")
            
        elif category == ErrorCategory.TYPE:
            if "NoneType" in message:
                suggestions.append("Add null check before accessing the object")
            if "'str'" in message and "'int'" in message:
                suggestions.append("Convert string to int using int() or vice versa")
            suggestions.append("Verify variable types match expected types")
            
        elif category == ErrorCategory.RUNTIME:
            if "KeyError" in message:
                key_match = re.search(r"KeyError: '?([^']+)'?", message)
                if key_match:
                    key = key_match.group(1)
                    suggestions.append(f"Check if key '{key}' exists using .get() or 'in' operator")
            if "IndexError" in message:
                suggestions.append("Check list/array bounds before accessing")
                suggestions.append("Verify the collection is not empty")
            if "ValueError" in message:
                suggestions.append("Validate input values before processing")
        
        elif category == ErrorCategory.NETWORK:
            suggestions.extend([
                "Check network connectivity",
                "Verify the URL/endpoint is correct",
                "Implement retry logic with backoff"
            ])
            
        elif category == ErrorCategory.RESOURCE:
            suggestions.extend([
                "Reduce memory usage or process data in chunks",
                "Close file handles and connections when done",
                "Check available system resources"
            ])
        
        return suggestions
    
    def validate_python_code(self, code: str) -> Tuple[bool, Optional[ErrorContext]]:
        """
        Validate Python code for syntax and basic errors.
        
        Args:
            code: Python source code to validate
            
        Returns:
            Tuple of (is_valid, error_context if invalid)
        """
        try:
            # Check syntax
            ast.parse(code)
            
            # Additional static checks
            issues = self._static_analysis(code)
            if issues:
                return False, ErrorContext(
                    error_type="StaticAnalysisWarning",
                    error_message="; ".join(issues),
                    category=ErrorCategory.LOGIC,
                    severity=ErrorSeverity.LOW,
                    suggested_fixes=issues
                )
            
            return True, None
            
        except SyntaxError as e:
            return False, self.parse_error(e, code)
    
    def _static_analysis(self, code: str) -> List[str]:
        """Perform basic static analysis on code"""
        issues = []
        lines = code.split('\n')
        
        for i, line in enumerate(lines, 1):
            # Check for common issues
            if 'import *' in line:
                issues.append(f"Line {i}: Avoid 'import *', use explicit imports")
            
            if re.search(r'except\s*:', line) and 'Exception' not in line:
                issues.append(f"Line {i}: Bare 'except:' catches all exceptions, be more specific")
            
            if 'eval(' in line or 'exec(' in line:
                issues.append(f"Line {i}: Avoid eval()/exec() for security reasons")
            
            # Check for potential None issues
            if re.search(r'\.split\(|\.strip\(|\.lower\(', line):
                if 'if ' not in lines[max(0, i-2):i] and 'and ' not in line:
                    # This is a simple heuristic, may have false positives
                    pass
        
        return issues
    
    def execute_with_retry(
        self,
        func: Callable,
        args: tuple = (),
        kwargs: dict = None,
        config: RetryConfig = None,
        on_error: Callable[[ErrorContext], Optional[str]] = None
    ) -> Tuple[bool, Any, List[ErrorContext]]:
        """
        Execute a function with retry logic and error handling.
        
        Args:
            func: Function to execute
            args: Positional arguments
            kwargs: Keyword arguments
            config: Retry configuration
            on_error: Optional callback when error occurs, can return modified code/args
            
        Returns:
            Tuple of (success, result/None, list of errors encountered)
        """
        if kwargs is None:
            kwargs = {}
        if config is None:
            config = RetryConfig()
        
        errors = []
        delay = config.initial_delay
        
        for attempt in range(config.max_retries + 1):
            try:
                result = func(*args, **kwargs)
                
                if errors:
                    logger.info(
                        f"Function succeeded after {attempt} retries "
                        f"(errors: {[e.error_type for e in errors]})"
                    )
                
                self.correction_stats["successful_corrections"] += len(errors)
                return True, result, errors
                
            except config.skip_exceptions:
                # Re-raise exceptions that should not be retried
                raise
                
            except config.retry_on_exceptions as e:
                error_context = self.parse_error(e)
                errors.append(error_context)
                
                if attempt < config.max_retries:
                    # Call error handler if provided
                    if on_error:
                        fix_result = on_error(error_context)
                        if fix_result:
                            logger.info(f"Applying fix: {fix_result[:100]}...")
                    
                    logger.warning(
                        f"Attempt {attempt + 1}/{config.max_retries + 1} failed: "
                        f"{error_context.error_type}: {error_context.error_message}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    
                    time.sleep(delay)
                    
                    if config.exponential_backoff:
                        delay = min(delay * config.backoff_multiplier, config.max_delay)
                else:
                    logger.error(
                        f"All {config.max_retries + 1} attempts failed. "
                        f"Last error: {error_context.error_type}: {error_context.error_message}"
                    )
        
        self.correction_stats["failed_corrections"] += 1
        return False, None, errors
    
    def attempt_auto_fix(
        self, 
        code: str, 
        error_context: ErrorContext
    ) -> Tuple[bool, Optional[str]]:
        """
        Attempt to automatically fix code based on error.
        
        Args:
            code: Original code
            error_context: Error that occurred
            
        Returns:
            Tuple of (was_fixed, fixed_code or None)
        """
        fixed_code = code
        was_fixed = False
        
        # Try category-specific fixes
        if error_context.category == ErrorCategory.IMPORT:
            fixed_code, was_fixed = self._fix_import_error(code, error_context)
        
        elif error_context.category == ErrorCategory.SYNTAX:
            fixed_code, was_fixed = self._fix_syntax_error(code, error_context)
        
        elif error_context.category == ErrorCategory.TYPE:
            fixed_code, was_fixed = self._fix_type_error(code, error_context)
        
        # If local fixes didn't work, try LLM if available
        if not was_fixed and self.llm_client:
            fixed_code, was_fixed = self._llm_fix(code, error_context)
        
        return was_fixed, fixed_code if was_fixed else None
    
    def _fix_import_error(self, code: str, error: ErrorContext) -> Tuple[str, bool]:
        """Attempt to fix import errors"""
        # Extract module name
        module_match = re.search(r"No module named '(\w+)'", error.error_message)
        if module_match:
            module = module_match.group(1)
            
            # Common module name corrections
            corrections = {
                "cv2": "opencv-python",
                "sklearn": "scikit-learn",
                "PIL": "Pillow",
                "yaml": "PyYAML",
            }
            
            pip_name = corrections.get(module, module)
            
            # Try to install the module
            try:
                logger.info(f"Attempting to install missing module: {pip_name}")
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pip_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return code, True  # Code unchanged, but module installed
            except subprocess.CalledProcessError:
                logger.warning(f"Failed to install {pip_name}")
        
        return code, False
    
    def _fix_syntax_error(self, code: str, error: ErrorContext) -> Tuple[str, bool]:
        """Attempt to fix syntax errors"""
        lines = code.split('\n')
        line_num = error.line_number
        
        if not line_num or line_num > len(lines):
            return code, False
        
        error_line = lines[line_num - 1]
        
        # Fix common syntax issues
        
        # Missing colon at end of control structures
        if re.match(r'^\s*(if|elif|else|for|while|def|class|try|except|finally|with)\b', error_line):
            if not error_line.rstrip().endswith(':'):
                lines[line_num - 1] = error_line.rstrip() + ':'
                return '\n'.join(lines), True
        
        # Unmatched parentheses
        open_parens = error_line.count('(') - error_line.count(')')
        if open_parens > 0:
            lines[line_num - 1] = error_line.rstrip() + ')' * open_parens
            return '\n'.join(lines), True
        
        # Unmatched brackets
        open_brackets = error_line.count('[') - error_line.count(']')
        if open_brackets > 0:
            lines[line_num - 1] = error_line.rstrip() + ']' * open_brackets
            return '\n'.join(lines), True
        
        return code, False
    
    def _fix_type_error(self, code: str, error: ErrorContext) -> Tuple[str, bool]:
        """Attempt to fix type errors"""
        # This is complex and usually requires understanding context
        # For now, we'll leave complex fixes to the LLM
        return code, False
    
    def _llm_fix(self, code: str, error: ErrorContext) -> Tuple[str, bool]:
        """Use LLM to fix code"""
        if not self.llm_client:
            return code, False
        
        prompt = f"""Fix the following Python code that has an error.

ERROR TYPE: {error.error_type}
ERROR MESSAGE: {error.error_message}
LINE NUMBER: {error.line_number}

CODE:
```python
{code}
```

TRACEBACK:
{error.full_traceback}

Please provide ONLY the corrected Python code, no explanations.
```python
"""
        
        try:
            response = self.llm_client.generate(prompt)
            
            # Extract code from response
            code_match = re.search(r'```python\n?(.*?)\n?```', response, re.DOTALL)
            if code_match:
                fixed_code = code_match.group(1)
                
                # Validate the fix
                is_valid, _ = self.validate_python_code(fixed_code)
                if is_valid:
                    return fixed_code, True
            
        except Exception as e:
            logger.warning(f"LLM fix failed: {e}")
        
        return code, False
    
    def get_correction_stats(self) -> Dict[str, Any]:
        """Get statistics about corrections made"""
        return {
            **self.correction_stats,
            "correction_rate": (
                self.correction_stats["successful_corrections"] / 
                max(1, self.correction_stats["total_errors"])
            ) * 100,
            "recent_errors": [
                {
                    "type": e.error_type,
                    "category": e.category.value,
                    "message": e.error_message[:100]
                }
                for e in self.error_history[-10:]
            ]
        }
    
    def reset_stats(self):
        """Reset correction statistics"""
        self.error_history = []
        self.correction_stats = {
            "total_errors": 0,
            "successful_corrections": 0,
            "failed_corrections": 0,
            "by_category": {}
        }


# Convenience function for wrapping with retry
def with_self_correction(
    max_retries: int = 3,
    auto_fix: bool = True,
    validate_before: bool = True
):
    """
    Decorator to add self-correction to any function.
    
    Args:
        max_retries: Maximum retry attempts
        auto_fix: Whether to attempt automatic fixes
        validate_before: Validate code before execution (if applicable)
    """
    engine = SelfCorrectionEngine()
    config = RetryConfig(max_retries=max_retries)
    
    def decorator(func):
        def wrapper(*args, **kwargs):
            def error_handler(error_context):
                if auto_fix and 'code' in kwargs:
                    success, fixed = engine.attempt_auto_fix(kwargs['code'], error_context)
                    if success:
                        kwargs['code'] = fixed
                        return fixed
                return None
            
            success, result, errors = engine.execute_with_retry(
                func, args, kwargs, config, error_handler
            )
            
            if not success:
                raise RuntimeError(
                    f"Function failed after {max_retries + 1} attempts. "
                    f"Errors: {[e.error_message for e in errors]}"
                )
            
            return result
        
        return wrapper
    return decorator


# Singleton instance for global use
correction_engine = SelfCorrectionEngine()
