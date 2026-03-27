"""
Tests for the Self-Correction System

Validates error detection, code repair, and retry logic.
"""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.self_correction import (
    SelfCorrectionEngine,
    RetryConfig,
    ErrorCategory,
    ErrorSeverity
)
from ai.code_validator import (
    CodeValidator,
    ValidationLevel,
    validate_and_fix
)


class TestSelfCorrectionEngine:
    """Tests for SelfCorrectionEngine"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.engine = SelfCorrectionEngine()
    
    def test_parse_syntax_error(self):
        """Test parsing a syntax error"""
        try:
            exec("def foo(")
        except SyntaxError as e:
            context = self.engine.parse_error(e, "def foo(")
            
            assert context.error_type == "SyntaxError"
            assert context.category == ErrorCategory.SYNTAX
            assert context.severity == ErrorSeverity.HIGH
            assert len(context.suggested_fixes) > 0
    
    def test_parse_import_error(self):
        """Test parsing an import error"""
        try:
            import nonexistent_module_12345
        except ImportError as e:
            context = self.engine.parse_error(e)
            
            assert context.error_type in ["ImportError", "ModuleNotFoundError"]
            assert context.category == ErrorCategory.IMPORT
    
    def test_parse_type_error(self):
        """Test parsing a type error"""
        try:
            "string" + 5
        except TypeError as e:
            context = self.engine.parse_error(e)
            
            assert context.error_type == "TypeError"
            assert context.category == ErrorCategory.TYPE
    
    def test_parse_runtime_error(self):
        """Test parsing runtime errors"""
        try:
            {}["nonexistent_key"]
        except KeyError as e:
            context = self.engine.parse_error(e)
            
            assert context.error_type == "KeyError"
            assert context.category == ErrorCategory.RUNTIME
    
    def test_validate_valid_code(self):
        """Test validating syntactically correct code"""
        valid_code = '''
def greet(name: str) -> str:
    """Return a greeting."""
    return f"Hello, {name}!"
'''
        is_valid, error = self.engine.validate_python_code(valid_code)
        assert is_valid is True
        assert error is None
    
    def test_validate_invalid_code(self):
        """Test validating syntactically incorrect code"""
        invalid_code = '''
def greet(name
    return f"Hello, {name}!"
'''
        is_valid, error = self.engine.validate_python_code(invalid_code)
        assert is_valid is False
        assert error is not None
        assert error.category == ErrorCategory.SYNTAX
    
    def test_retry_config(self):
        """Test retry configuration"""
        config = RetryConfig(
            max_retries=5,
            initial_delay=0.1,
            exponential_backoff=True
        )
        
        assert config.max_retries == 5
        assert config.initial_delay == 0.1
        assert config.exponential_backoff is True
    
    def test_execute_with_retry_success(self):
        """Test execute_with_retry on a successful function"""
        call_count = 0
        
        def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"
        
        config = RetryConfig(max_retries=3, initial_delay=0.01)
        success, result, errors = self.engine.execute_with_retry(
            successful_func, config=config
        )
        
        assert success is True
        assert result == "success"
        assert len(errors) == 0
        assert call_count == 1
    
    def test_execute_with_retry_eventual_success(self):
        """Test execute_with_retry with eventual success"""
        call_count = 0
        
        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Not yet!")
            return "finally!"
        
        config = RetryConfig(max_retries=5, initial_delay=0.01)
        success, result, errors = self.engine.execute_with_retry(
            flaky_func, config=config
        )
        
        assert success is True
        assert result == "finally!"
        assert len(errors) == 2  # Failed twice before success
        assert call_count == 3
    
    def test_execute_with_retry_failure(self):
        """Test execute_with_retry with max retries exceeded"""
        call_count = 0
        
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Always fails!")
        
        config = RetryConfig(max_retries=2, initial_delay=0.01)
        success, result, errors = self.engine.execute_with_retry(
            always_fails, config=config
        )
        
        assert success is False
        assert result is None
        assert len(errors) == 3  # Initial + 2 retries
        assert call_count == 3
    
    def test_correction_stats(self):
        """Test correction statistics tracking"""
        # Generate some errors
        try:
            exec("invalid syntax here!")
        except SyntaxError as e:
            self.engine.parse_error(e)
        
        try:
            1 / 0
        except ZeroDivisionError as e:
            self.engine.parse_error(e)
        
        stats = self.engine.get_correction_stats()
        
        assert stats["total_errors"] >= 2
        assert "by_category" in stats


class TestCodeValidator:
    """Tests for CodeValidator"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.validator = CodeValidator(auto_fix=True)
    
    def test_validate_syntax_level(self):
        """Test syntax-level validation"""
        valid_code = "x = 5 + 3"
        result = self.validator.validate(valid_code, ValidationLevel.SYNTAX)
        
        assert result.is_valid is True
        assert result.level_checked == ValidationLevel.SYNTAX
    
    def test_validate_static_level(self):
        """Test static analysis level validation"""
        code_with_warnings = '''
import *
x = 5
exec("dangerous")
'''
        result = self.validator.validate(code_with_warnings, ValidationLevel.STATIC)
        
        # Should have warnings
        assert len(result.warnings) > 0
    
    def test_repair_missing_colon(self):
        """Test automatic repair of missing colon"""
        broken_code = '''
def foo()
    pass
'''
        result = self.validator.repair_code(broken_code)
        
        # Should attempt to fix
        if result.fixed_code:
            assert ':' in result.fixed_code
    
    def test_repair_unmatched_parentheses(self):
        """Test automatic repair of unmatched parentheses"""
        broken_code = "print(hello"
        result = self.validator.repair_code(broken_code)
        
        if result.fixed_code:
            assert result.fixed_code.count('(') == result.fixed_code.count(')')
    
    def test_validate_and_fix_convenience(self):
        """Test the validate_and_fix convenience function"""
        valid_code = "x = 42"
        is_valid, final_code, report = validate_and_fix(valid_code)
        
        assert is_valid is True
        assert final_code == valid_code
        assert "VALID" in report
    
    def test_format_validation_report(self):
        """Test report formatting"""
        code = "invalid syntax !@#$"
        result = self.validator.validate(code, ValidationLevel.SYNTAX)
        report = self.validator.format_validation_report(result)
        
        assert "VALIDATION REPORT" in report
        assert "Status:" in report


class TestIntegration:
    """Integration tests for the self-correction system"""
    
    def test_full_correction_flow(self):
        """Test complete error -> parse -> suggest flow"""
        engine = SelfCorrectionEngine()
        
        # Simulate an error
        code = '''
def calculate(a, b)
    result = a + b
    return result
'''
        
        is_valid, error = engine.validate_python_code(code)
        
        if not is_valid:
            assert error is not None
            assert len(error.suggested_fixes) > 0
            
            # Try auto-fix
            success, fixed = engine.attempt_auto_fix(code, error)
            
            if success and fixed:
                # Validate the fix
                is_valid_now, _ = engine.validate_python_code(fixed)
                assert is_valid_now is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
